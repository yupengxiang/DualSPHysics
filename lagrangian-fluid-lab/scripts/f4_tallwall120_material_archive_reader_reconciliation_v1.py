#!/usr/bin/env python3
"""Bounded F4 Tallwall120 archives/reader-manifest reconciliation intake.

This is a read-only source-identity contract for the DEV_07 coarse material
proposal.  It reads only bounded JSON metadata from the archives-v1 archive,
archives-v2 archive, the current Core collection manifest, the proposal, and
the historical reader smoke receipt.  The trajectory HDF5 is never opened,
read, or re-hashed here.

The contract deliberately treats the collection-path drift and stale reader
manifest digest as blocking.  It also observes the real root/scheduler
receipt paths but never accepts them as authority: a missing fresh root
receipt or scheduler-owned host-I/O reservation keeps the report
fail-closed, with no solver/worker/GPU/queue start and no fabricated receipt.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Mapping, Sequence


LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.core_strict_json import read_bounded_json_object  # noqa: E402


SCHEMA = "core.material.f4.tallwall120.archive_reader_reconciliation.v1"
RECORD_ID = "f4-tallwall120-material-archive-reader-reconciliation-v1-2026-09-29"
CREATED_AT = "2026-09-29"
DEFAULT_OBSERVED_AT_UTC = "2026-09-29T00:00:00Z"

FAMILY = "F4"
SCOPE_ID = "F4_resting_pool_laminar_tallwall120_x_v1"
CASE_ID = f"{SCOPE_ID}_DEV_07"
TARGET_SOURCE = (
    "campaigns/core-v1/cfd/f4-tallwall120-production-archives-v2/"
    "f4-tallwall120-production-dev-07/product/trajectory.h5"
)
COLLECTION_SOURCE = (
    "campaigns/core-v1/cfd/f4-tallwall120-production-archives-v1/"
    "f4-tallwall120-production-dev-07/product/trajectory.h5"
)
SOURCE_SHA256 = "6ae8ca7062e1fa15779fc9ad491d1117455700315c6a1ef4a12326458f0976ae"
SOURCE_BYTES = 2_067_911_708

PROPOSAL = Path("reports/F4-TALLWALL120-MATERIAL-COARSE-PROPOSAL-2026-09-28.json")
ARCHIVES = {
    "v1": Path(
        "campaigns/core-v1/cfd/f4-tallwall120-production-archives-v1/"
        "f4-tallwall120-production-dev-07/archive.json"
    ),
    "v2": Path(
        "campaigns/core-v1/cfd/f4-tallwall120-production-archives-v2/"
        "f4-tallwall120-production-dev-07/archive.json"
    ),
}
COLLECTION = Path(
    "campaigns/core-v1/cfd/f4-tallwall120-production-root-v1/"
    "collection-refresh-terminal32-formal-v1.json"
)
READER = Path("reports/F4-TALLWALL120-CORE-READER-SMOKE-2026-09-28.json")
ROOT_RECEIPT = Path(
    "campaigns/core-v1/material/evidence/"
    "f4-tallwall120-material-root-scheduler-intake-v1/fresh-root-receipt.json"
)
SCHEDULER_RECEIPT = Path(
    "campaigns/core-v1/material/evidence/"
    "f4-tallwall120-material-root-scheduler-intake-v1/"
    "scheduler-host-io-reservation.json"
)

DEFAULT_REPORT = Path(
    "reports/F4-TALLWALL120-MATERIAL-ARCHIVE-READER-RECONCILIATION-V1-2026-09-29.json"
)
DEFAULT_MARKDOWN = Path(
    "reports/F4-TALLWALL120-MATERIAL-ARCHIVE-READER-RECONCILIATION-V1-2026-09-29.zh-CN.md"
)

MAX_JSON_BYTES = 8 * 1024 * 1024
SHA256 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def _is_int(value: Any) -> bool:
    return type(value) is int


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _safe_path(root: Path, relative: Path) -> Path:
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError(f"input path is not repository-relative: {relative}")
    root = root.resolve()
    parent = (root / relative.parent).resolve()
    parent.relative_to(root)
    return parent / relative.name


def _read_json(root: Path, relative: Path, *, role: str) -> tuple[dict[str, Any], dict[str, Any], str | None]:
    reference: dict[str, Any] = {
        "role": role,
        "path": relative.as_posix(),
        "exists": False,
        "bytes": None,
        "sha256": None,
        "bounded_json": True,
        "content_read": False,
        "error": None,
    }
    try:
        target = _safe_path(root, relative)
        payload, _safe_target, digest = read_bounded_json_object(
            target,
            max_bytes=MAX_JSON_BYTES,
            label=role,
        )
    except (OSError, ValueError, UnicodeError) as error:
        reference["error"] = type(error).__name__
        return {}, reference, reference["error"]
    reference.update(
        {
            "exists": True,
            "bytes": target.stat().st_size,
            "sha256": digest,
            "content_read": True,
        }
    )
    return dict(payload), reference, None


def _presence(root: Path, relative: Path, *, role: str) -> dict[str, Any]:
    reference: dict[str, Any] = {
        "role": role,
        "path": relative.as_posix(),
        "exists": False,
        "regular_file": False,
        "read": False,
        "accepted_as_authority": False,
    }
    try:
        target = _safe_path(root, relative)
        info = os.lstat(target)
    except OSError as error:
        reference["error"] = type(error).__name__
        return reference
    reference["exists"] = True
    reference["regular_file"] = stat.S_ISREG(info.st_mode)
    return reference


def _archive_projection(payload: Mapping[str, Any], reference: Mapping[str, Any], *, variant: str) -> dict[str, Any]:
    outputs = payload.get("outputs")
    trajectories = [
        item for item in outputs
        if isinstance(item, Mapping) and item.get("path") == "product/trajectory.h5"
    ] if isinstance(outputs, list) else []
    trajectory = dict(trajectories[0]) if len(trajectories) == 1 else {}
    contract_valid = bool(
        payload.get("schema") == "core.verified_archive.v1"
        and payload.get("execution_status") == "succeeded"
        and payload.get("job_id") == "f4-tallwall120-production-dev-07"
        and payload.get("qualification_claim") == "none"
        and len(trajectories) == 1
        and trajectory.get("path") == "product/trajectory.h5"
        and _is_int(trajectory.get("bytes"))
        and trajectory.get("bytes") == SOURCE_BYTES
        and trajectory.get("sha256") == SOURCE_SHA256
    )
    return {
        "variant": variant,
        "path": reference.get("path"),
        "manifest_sha256": reference.get("sha256"),
        "manifest_bytes": reference.get("bytes"),
        "schema": payload.get("schema"),
        "execution_status": payload.get("execution_status"),
        "job_id": payload.get("job_id"),
        "receipt_sha256": payload.get("receipt_sha256"),
        "trajectory": {
            "path": trajectory.get("path"),
            "bytes": trajectory.get("bytes"),
            "sha256": trajectory.get("sha256"),
        },
        "contract_valid": contract_valid,
    }


def _proposal_projection(payload: Mapping[str, Any]) -> dict[str, Any]:
    target = _mapping(payload.get("target"))
    source = _mapping(payload.get("source_manifest_contract"))
    direct = _mapping(source.get("direct_source_manifest"))
    trajectory = _mapping(direct.get("trajectory_output"))
    return {
        "schema": payload.get("schema"),
        "status": payload.get("status"),
        "proposal_only": payload.get("proposal_only"),
        "target": {
            "family": target.get("family"),
            "scope_id": target.get("scope_id"),
            "case_id": target.get("case_id"),
            "source_hdf5": target.get("source_hdf5"),
            "source_sha256": target.get("source_sha256"),
            "source_bytes": target.get("source_bytes"),
        },
        "direct_source_manifest": {
            "path": direct.get("path"),
            "sha256": direct.get("sha256"),
            "trajectory": {
                "path": trajectory.get("path"),
                "bytes": trajectory.get("bytes"),
                "sha256": trajectory.get("sha256"),
            },
            "exact_target_binding": direct.get("exact_target_binding"),
        },
    }


def _collection_projection(payload: Mapping[str, Any], reference: Mapping[str, Any]) -> dict[str, Any]:
    cases = payload.get("cases")
    rows = [row for row in cases if isinstance(row, Mapping) and row.get("case_id") == CASE_ID] if isinstance(cases, list) else []
    row = rows[0] if len(rows) == 1 else {}
    trajectory = _mapping(row.get("trajectory"))
    return {
        "manifest_path": reference.get("path"),
        "manifest_sha256": reference.get("sha256"),
        "manifest_bytes": reference.get("bytes"),
        "case_count": len(cases) if isinstance(cases, list) else None,
        "matching_case_rows": len(rows),
        "case_id": row.get("case_id"),
        "trajectory": {
            "path": trajectory.get("path"),
            "bytes": trajectory.get("bytes"),
            "sha256": trajectory.get("sha256"),
        },
        "reader_eligible": row.get("reader_eligible"),
        "status": row.get("status"),
    }


def _reader_projection(payload: Mapping[str, Any], collection_reference: Mapping[str, Any]) -> dict[str, Any]:
    result = _mapping(payload.get("reader_result"))
    return {
        "manifest": payload.get("manifest"),
        "recorded_manifest_sha256": payload.get("manifest_sha256"),
        "current_manifest_sha256": collection_reference.get("sha256"),
        "reader_result": {
            "dataset_opened": result.get("dataset_opened"),
            "reader_formal_eligible": result.get("reader_formal_eligible"),
            "diagnostic_only": result.get("diagnostic_only"),
            "qualification_credit": result.get("qualification_credit"),
        },
    }


def _checks(
    proposal: Mapping[str, Any],
    archives: Mapping[str, Mapping[str, Any]],
    collection: Mapping[str, Any],
    reader: Mapping[str, Any],
) -> dict[str, bool]:
    target = _mapping(proposal.get("target"))
    direct = _mapping(proposal.get("direct_source_manifest"))
    direct_trajectory = _mapping(direct.get("trajectory"))
    v1 = archives.get("v1", {})
    v2 = archives.get("v2", {})
    v1_trajectory = _mapping(v1.get("trajectory"))
    v2_trajectory = _mapping(v2.get("trajectory"))
    collection_trajectory = _mapping(collection.get("trajectory"))
    reader_result = _mapping(reader.get("reader_result"))
    return {
        "proposal_target_exact": (
            proposal.get("schema") == "core.material.f4.tallwall120.coarse_proposal.v1"
            and proposal.get("status") == "blocked_fail_closed"
            and proposal.get("proposal_only") is True
            and target.get("family") == FAMILY
            and target.get("scope_id") == SCOPE_ID
            and target.get("case_id") == CASE_ID
            and target.get("source_hdf5") == TARGET_SOURCE
            and target.get("source_sha256") == SOURCE_SHA256
            and target.get("source_bytes") == SOURCE_BYTES
        ),
        "proposal_direct_archive_v2_exact": (
            direct.get("path") == ARCHIVES["v2"].as_posix()
            and direct.get("sha256") == v2.get("manifest_sha256")
            and direct_trajectory.get("path") == "product/trajectory.h5"
            and direct_trajectory.get("bytes") == SOURCE_BYTES
            and direct_trajectory.get("sha256") == SOURCE_SHA256
            and direct.get("exact_target_binding") is True
        ),
        "archive_v1_manifest_contract_valid": v1.get("contract_valid") is True,
        "archive_v2_manifest_contract_valid": v2.get("contract_valid") is True,
        "archive_v1_v2_artifact_identity_exact": (
            v1_trajectory.get("path") == v2_trajectory.get("path") == "product/trajectory.h5"
            and v1_trajectory.get("bytes") == v2_trajectory.get("bytes") == SOURCE_BYTES
            and v1_trajectory.get("sha256") == v2_trajectory.get("sha256") == SOURCE_SHA256
        ),
        "archive_v1_v2_manifest_bytes_distinct": (
            _is_sha(v1.get("manifest_sha256"))
            and _is_sha(v2.get("manifest_sha256"))
            and v1.get("manifest_sha256") != v2.get("manifest_sha256")
        ),
        "collection_manifest_current_sha_bound": (
            collection.get("manifest_path") == COLLECTION.as_posix()
            and _is_sha(collection.get("manifest_sha256"))
        ),
        "collection_case_unique": (
            collection.get("matching_case_rows") == 1
            and collection.get("case_id") == CASE_ID
        ),
        "collection_case_source_sha_exact": (
            collection_trajectory.get("sha256") == SOURCE_SHA256
            and collection_trajectory.get("bytes") == SOURCE_BYTES
        ),
        "collection_case_source_path_exact": collection_trajectory.get("path") == TARGET_SOURCE,
        "reader_manifest_path_exact": reader.get("manifest") == COLLECTION.as_posix(),
        "reader_manifest_sha_exact": (
            reader.get("recorded_manifest_sha256") == reader.get("current_manifest_sha256")
            and _is_sha(reader.get("current_manifest_sha256"))
        ),
        "reader_formal_gate_closed": (
            reader_result.get("reader_formal_eligible") is False
            and reader_result.get("diagnostic_only") is True
            and reader_result.get("qualification_credit") == 0
        ),
    }


def _execution_controls() -> dict[str, Any]:
    return {
        "bounded_json_only": True,
        "max_json_bytes": MAX_JSON_BYTES,
        "archive_hdf5_opened": False,
        "source_hdf5_opened": False,
        "source_hdf5_read": False,
        "source_hdf5_hash_recomputed": False,
        "fresh_root_receipt_written": False,
        "scheduler_receipt_written": False,
        "material_sidecar_written": False,
        "solver_started": False,
        "worker_started": False,
        "native_started": False,
        "gpu_started": False,
        "queue_or_scheduler_started": False,
        "registry_mutations": 0,
        "ledger_mutations": 0,
        "denominator_mutations": 0,
        "gate_mutations": 0,
        "completion_mutations": 0,
        "plan_mutations": 0,
    }


def build_report(root: str | Path = LAB_ROOT, *, observed_at_utc: str = DEFAULT_OBSERVED_AT_UTC) -> dict[str, Any]:
    root = Path(root).resolve()
    documents = {
        "proposal": (PROPOSAL, "F4 coarse proposal"),
        "archive_v1": (ARCHIVES["v1"], "F4 archives-v1 DEV_07 archive"),
        "archive_v2": (ARCHIVES["v2"], "F4 archives-v2 DEV_07 archive"),
        "collection": (COLLECTION, "F4 current Core collection manifest"),
        "reader": (READER, "F4 reader smoke receipt"),
    }
    payloads: dict[str, dict[str, Any]] = {}
    references: dict[str, dict[str, Any]] = {}
    input_errors: list[str] = []
    for name, (path, role) in documents.items():
        payload, reference, error = _read_json(root, path, role=role)
        payloads[name] = payload
        references[name] = reference
        if error:
            input_errors.append(f"{name}:{error}")

    proposal = _proposal_projection(payloads["proposal"])
    archives = {
        variant: _archive_projection(payloads[f"archive_{variant}"], references[f"archive_{variant}"], variant=variant)
        for variant in ("v1", "v2")
    }
    collection = _collection_projection(payloads["collection"], references["collection"])
    reader = _reader_projection(payloads["reader"], references["collection"])
    checks = _checks(proposal, archives, collection, reader)

    root_reference = _presence(root, ROOT_RECEIPT, role="fresh root authorization receipt")
    scheduler_reference = _presence(root, SCHEDULER_RECEIPT, role="scheduler-owned host-I/O reservation")
    root_present = root_reference["exists"] is True and root_reference["regular_file"] is True
    scheduler_present = scheduler_reference["exists"] is True and scheduler_reference["regular_file"] is True

    source_ready = bool(
        checks["proposal_target_exact"]
        and checks["proposal_direct_archive_v2_exact"]
        and checks["archive_v1_manifest_contract_valid"]
        and checks["archive_v2_manifest_contract_valid"]
        and checks["archive_v1_v2_artifact_identity_exact"]
        and checks["collection_manifest_current_sha_bound"]
        and checks["collection_case_unique"]
        and checks["collection_case_source_sha_exact"]
        and checks["collection_case_source_path_exact"]
        and checks["reader_manifest_path_exact"]
        and checks["reader_manifest_sha_exact"]
    )

    findings: list[dict[str, Any]] = []
    if not checks["collection_case_source_path_exact"]:
        findings.append(
            {
                "finding": "collection_manifest_archives_v1_vs_archives_v2_path_drift",
                "severity": "blocking",
                "observed": collection.get("trajectory", {}).get("path"),
                "expected": TARGET_SOURCE,
                "detail": "the current DEV_07 collection row still points at archives-v1 while the proposal and archives-v2 point at archives-v2",
            }
        )
    if not checks["reader_manifest_sha_exact"]:
        findings.append(
            {
                "finding": "reader_manifest_sha_stale",
                "severity": "blocking",
                "observed": reader.get("recorded_manifest_sha256"),
                "expected": reader.get("current_manifest_sha256"),
                "detail": "the reader smoke receipt does not bind the exact current collection manifest bytes",
            }
        )
    if not checks["archive_v1_v2_artifact_identity_exact"]:
        findings.append(
            {
                "finding": "archives_v1_v2_artifact_identity_drift",
                "severity": "blocking",
                "detail": "archives-v1 and archives-v2 do not declare the same bounded trajectory artifact identity",
            }
        )
    if not root_present:
        findings.append(
            {
                "finding": "fresh_root_receipt_missing",
                "severity": "blocking",
                "path": ROOT_RECEIPT.as_posix(),
                "detail": "no real fresh root-owned one-use authorization receipt is present",
            }
        )
    if not scheduler_present:
        findings.append(
            {
                "finding": "scheduler_host_io_reservation_missing",
                "severity": "blocking",
                "path": SCHEDULER_RECEIPT.as_posix(),
                "detail": "no real scheduler-owned host-I/O reservation is present; GPU capacity cannot substitute for it",
            }
        )
    blockers = [item["finding"] for item in findings if item.get("severity") == "blocking"]
    blockers.extend(f"input:{item}" for item in input_errors)
    blockers = list(dict.fromkeys(blockers))

    return {
        "schema": SCHEMA,
        "record_id": RECORD_ID,
        "created_at": CREATED_AT,
        "observed_at_utc": observed_at_utc,
        "status": "blocked_fail_closed",
        "decision": "diagnostic_only_archive_reader_reconciliation",
        "scope": {"family": FAMILY, "scope_id": SCOPE_ID, "case_id": CASE_ID, "split": "train"},
        "inputs": references,
        "proposal": proposal,
        "archives": archives,
        "collection": collection,
        "reader": reader,
        "checks": checks,
        "source_reconciliation": {
            "ready": source_ready,
            "archives_v1_v2_artifact_identity_exact": checks["archive_v1_v2_artifact_identity_exact"],
            "collection_path_reconciled": checks["collection_case_source_path_exact"],
            "reader_manifest_sha_reconciled": checks["reader_manifest_sha_exact"],
        },
        "root_scheduler_prerequisites": {
            "fresh_root_receipt": root_reference,
            "scheduler_host_io_reservation": scheduler_reference,
            "fresh_root_receipt_present": root_present,
            "scheduler_host_io_reservation_present": scheduler_present,
            "pair_cross_bound": False,
            "accepted_as_authority": False,
        },
        "authority": {
            "fresh_root_receipt_credible": False,
            "scheduler_owned_host_io_receipt_credible": False,
            "pair_cross_bound": False,
            "launch_allowed": False,
            "worker_launch_authorized": False,
            "formal": False,
            "T1": False,
            "T2": False,
            "credit": 0,
        },
        "findings": findings,
        "blockers": blockers,
        "execution_controls": _execution_controls(),
        "next_safe_action": (
            "由 collection authority 以不可变新回执把 DEV_07 collection row 重绑定到 archives-v2，"
            "由 reader authority 以同一 collection manifest 原始字节重做 smoke receipt；"
            "之后仍须由 root owner 与 scheduler 分别提供真实且 cross-bound 的 fresh root receipt 和 scheduler-owned host-I/O reservation。"
            "在全部条件满足前，不得启动 material sidecar、solver、worker、GPU 或 queue。"
        ),
    }


def validate_report(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    required = {
        "schema", "record_id", "created_at", "observed_at_utc", "status", "decision", "scope",
        "inputs", "proposal", "archives", "collection", "reader", "checks", "source_reconciliation",
        "root_scheduler_prerequisites", "authority", "findings", "blockers", "execution_controls",
        "next_safe_action",
    }
    if not isinstance(report, Mapping) or set(report) != required:
        return ["report.fields"]
    if report.get("schema") != SCHEMA:
        errors.append("schema")
    if report.get("record_id") != RECORD_ID:
        errors.append("record_id")
    if report.get("created_at") != CREATED_AT:
        errors.append("created_at")
    if report.get("status") != "blocked_fail_closed":
        errors.append("status")
    if report.get("decision") != "diagnostic_only_archive_reader_reconciliation":
        errors.append("decision")
    if report.get("scope") != {"family": FAMILY, "scope_id": SCOPE_ID, "case_id": CASE_ID, "split": "train"}:
        errors.append("scope")
    checks = report.get("checks")
    if not isinstance(checks, Mapping) or not all(type(value) is bool for value in checks.values()):
        errors.append("checks")
    source = _mapping(report.get("source_reconciliation"))
    if source.get("ready") is not False:
        errors.append("source_reconciliation.ready")
    authority = _mapping(report.get("authority"))
    for key, expected in {
        "fresh_root_receipt_credible": False,
        "scheduler_owned_host_io_receipt_credible": False,
        "pair_cross_bound": False,
        "launch_allowed": False,
        "worker_launch_authorized": False,
        "formal": False,
        "T1": False,
        "T2": False,
        "credit": 0,
    }.items():
        actual = authority.get(key)
        if type(actual) is not type(expected) or actual != expected:
            errors.append(f"authority.{key}")
    controls = _mapping(report.get("execution_controls"))
    expected_false = {
        "archive_hdf5_opened", "source_hdf5_opened", "source_hdf5_read", "source_hdf5_hash_recomputed",
        "fresh_root_receipt_written", "scheduler_receipt_written", "material_sidecar_written", "solver_started",
        "worker_started", "native_started", "gpu_started", "queue_or_scheduler_started",
    }
    if controls.get("bounded_json_only") is not True or controls.get("max_json_bytes") != MAX_JSON_BYTES:
        errors.append("execution_controls.bounded_json")
    for key in expected_false:
        if controls.get(key) is not False:
            errors.append(f"execution_controls.{key}")
    for key in ("registry_mutations", "ledger_mutations", "denominator_mutations", "gate_mutations", "completion_mutations", "plan_mutations"):
        if controls.get(key) != 0:
            errors.append(f"execution_controls.{key}")
    prerequisites = _mapping(report.get("root_scheduler_prerequisites"))
    if prerequisites.get("pair_cross_bound") is not False or prerequisites.get("accepted_as_authority") is not False:
        errors.append("root_scheduler_prerequisites.authority")
    if not isinstance(report.get("findings"), list) or not isinstance(report.get("blockers"), list):
        errors.append("findings_blockers")
    return errors


def _write_new(path: str | Path, payload: bytes) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        stream.write(payload)
    return target


def render_markdown(report: Mapping[str, Any]) -> str:
    errors = validate_report(report)
    if errors:
        raise ValueError("invalid report: " + ", ".join(errors))
    checks = report["checks"]
    root = report["root_scheduler_prerequisites"]
    return "\n".join(
        [
            "# F4 Tallwall120 archives/reader reconciliation v1",
            "",
            f"- status：`{report['status']}`；source reconciliation ready：`{report['source_reconciliation']['ready']}`",
            f"- archives-v1/v2 artifact identity exact：`{checks['archive_v1_v2_artifact_identity_exact']}`；collection path exact：`{checks['collection_case_source_path_exact']}`",
            f"- reader manifest path exact：`{checks['reader_manifest_path_exact']}`；reader manifest SHA exact：`{checks['reader_manifest_sha_exact']}`",
            f"- fresh root receipt present：`{root['fresh_root_receipt_present']}`；scheduler host-I/O reservation present：`{root['scheduler_host_io_reservation_present']}`",
            "- authority：`launch_allowed=false`、`formal=false`、`T1=false`、`T2=false`、`credit=0`。",
            "- 本 intake 只读取有界 JSON metadata；不打开、读取或重哈希 trajectory HDF5，不启动 solver/worker/GPU/queue，不伪造 receipt。",
            "",
            "## Blockers",
            "",
            *[f"- `{item}`" for item in report["blockers"]],
            "",
            "## Next safe action",
            "",
            report["next_safe_action"],
            "",
        ]
    )


def write_outputs(report: Mapping[str, Any], report_path: str | Path = DEFAULT_REPORT, markdown_path: str | Path = DEFAULT_MARKDOWN) -> tuple[Path, Path]:
    errors = validate_report(report)
    if errors:
        raise ValueError("invalid report: " + ", ".join(errors))
    raw = (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    json_path = _write_new(report_path, raw)
    markdown = render_markdown(report).encode("utf-8")
    try:
        markdown_path_obj = _write_new(markdown_path, markdown)
    except Exception:
        json_path.unlink(missing_ok=True)
        raise
    return json_path, markdown_path_obj


def verify_report(path: str | Path = DEFAULT_REPORT, *, root: str | Path = LAB_ROOT) -> None:
    payload, _safe_path, _digest = read_bounded_json_object(path, max_bytes=MAX_JSON_BYTES, label="F4 archive-reader report")
    errors = validate_report(payload)
    if errors:
        raise ValueError("invalid report: " + ", ".join(errors))
    expected = build_report(root)
    if payload != expected:
        raise ValueError("report does not exactly match the current bounded inputs")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--verify-report", type=Path)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    if args.verify_report is not None:
        verify_report(args.verify_report, root=args.root)
        return 0
    report = build_report(args.root, observed_at_utc=DEFAULT_OBSERVED_AT_UTC)
    if args.write:
        write_outputs(report, args.output, args.markdown_output)
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
