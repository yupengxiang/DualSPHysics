#!/usr/bin/env python3
"""Read-only F4 Tallwall120 material/T2 RERUN3 gap audit.

This is a bounded gap report, not a receipt and not an admission or launch
adapter.  It reads the existing F4 readiness/security report, root/scheduler
and host-I/O contracts, terminal evidence intake, material sidecar contracts,
and their implementation bytes.  It never opens or hashes the trajectory
HDF5, creates a namespace or receipt, starts a worker/solver/GPU/queue, or
changes campaign state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


LAB_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "core.material.f4.tallwall120.coarse_t2.rerun3_gap_audit.v1"
OBSERVED_AT_UTC = "2026-09-29T00:00:00Z"
FAMILY = "F4"
SCOPE_ID = "F4_resting_pool_laminar_tallwall120_x_v1"
CASE_ID = f"{SCOPE_ID}_DEV_07"
SOURCE_HDF5 = (
    "campaigns/core-v1/cfd/f4-tallwall120-production-archives-v2/"
    "f4-tallwall120-production-dev-07/product/trajectory.h5"
)
SOURCE_SHA256 = "6ae8ca7062e1fa15779fc9ad491d1117455700315c6a1ef4a12326458f0976ae"
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_SOURCE_BYTES = 2 * 1024 * 1024

ANCHOR = Path(
    "reports/F4-TALLWALL120-MATERIAL-COARSE-T2-READINESS-SECURITY-AUDIT-"
    "2026-09-29-RERUN2.json"
)
REPORT_INPUTS = {
    "root_scheduler": Path(
        "reports/F4-TALLWALL120-MATERIAL-ROOT-SCHEDULER-INTAKE-V1-"
        "2026-09-29-RERUN1.json"
    ),
    "fresh_root_scheduler": Path(
        "reports/F4-TALLWALL120-MATERIAL-FRESH-ROOT-SCHEDULER-RECEIPT-"
        "CONTRACT-V1-2026-09-29-RERUN1.json"
    ),
    "external_receipt": Path(
        "reports/F4-TALLWALL120-MATERIAL-EXTERNAL-RECEIPT-INTAKE-V1-"
        "2026-09-29-RERUN1.json"
    ),
    "host_io": Path(
        "reports/F4-TALLWALL120-COARSE-HOST-IO-ADMISSION-PROJECTION-"
        "2026-09-28.json"
    ),
    "archive_reader": Path(
        "reports/F4-TALLWALL120-MATERIAL-ARCHIVE-READER-RECONCILIATION-"
        "V1-2026-09-29.json"
    ),
    "source_drift": Path(
        "reports/F4-TALLWALL120-MATERIAL-SOURCE-DRIFT-RECONCILIATION-"
        "V1-2026-09-28.json"
    ),
    "case_sidecar": Path(
        "reports/F4-TALLWALL120-MATERIAL-CASE-SIDECAR-INTAKE-V1-2026-09-28.json"
    ),
    "sidecar_matrix": Path(
        "reports/F4-TALLWALL120-MATERIAL-SIDECAR-MATRIX-CONTRACT-V1-2026-09-28.json"
    ),
    "terminal_evidence": Path(
        "reports/F4-TALLWALL120-MATERIAL-TERMINAL-EVIDENCE-INTAKE-V1-2026-09-28.json"
    ),
    "readiness_projection": Path(
        "reports/F4-TALLWALL120-MATERIAL-READINESS-PROJECTION-V1-2026-09-28.json"
    ),
    "t2_readiness": Path(
        "reports/F4-TALLWALL120-T2-READINESS-AUDIT-2026-09-28.json"
    ),
}
CODE_INPUTS = {
    "root_scheduler_contract": Path(
        "scripts/f4_tallwall120_material_root_scheduler_intake_v1.py"
    ),
    "fresh_root_scheduler_contract": Path(
        "scripts/f4_tallwall120_material_fresh_root_scheduler_receipt_contract_v1.py"
    ),
    "external_receipt_contract": Path(
        "scripts/f4_tallwall120_material_external_receipt_intake_v1.py"
    ),
    "host_io_contract": Path("scripts/f4_tallwall120_coarse_host_io_admission_v1.py"),
    "terminal_evidence_contract": Path(
        "scripts/f4_tallwall120_material_terminal_evidence_intake_v1.py"
    ),
    "material_sidecar_contract": Path(
        "scripts/f4_tallwall120_material_case_sidecar_intake_v1.py"
    ),
    "sidecar_matrix_contract": Path(
        "scripts/f4_tallwall120_material_sidecar_matrix_contract_v1.py"
    ),
}

DEFAULT_JSON = Path(
    "reports/F4-TALLWALL120-MATERIAL-COARSE-T2-RERUN3-GAP-2026-09-29.json"
)
DEFAULT_ZH = Path(
    "reports/F4-TALLWALL120-MATERIAL-COARSE-T2-RERUN3-GAP-2026-09-29.zh-CN.md"
)
DEFAULT_TEST = Path(
    "tests/test_f4_tallwall120_material_coarse_t2_rerun3_gap_audit_v1.py"
)
DEFAULT_SCRIPT = Path(
    "scripts/f4_tallwall120_material_coarse_t2_rerun3_gap_audit_v1.py"
)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _resolve(root: Path, relative: Path) -> Path:
    if relative.is_absolute():
        raise ValueError(f"absolute path is outside the F4 audit input set: {relative}")
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError(f"input escapes the lab root: {relative}") from error
    return candidate


def _read_bytes(root: Path, relative: Path, *, limit: int) -> tuple[Path, bytes]:
    path = _resolve(root, relative)
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(path)
    size = path.stat().st_size
    if size > limit:
        raise ValueError(f"input exceeds bounded size: {relative} ({size} bytes)")
    return path, path.read_bytes()


def _read_json(root: Path, relative: Path) -> tuple[Path, bytes, dict[str, Any]]:
    path, raw = _read_bytes(root, relative, limit=MAX_JSON_BYTES)
    value = json.loads(
        raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x))
    )
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {relative}")
    return path, raw, value


def _status(value: Mapping[str, Any]) -> Any:
    if value.get("status") is not None:
        return value.get("status")
    decision = value.get("decision")
    if isinstance(decision, str):
        return decision
    if isinstance(decision, Mapping):
        return decision.get("status") or decision.get("readiness_status")
    return None


def _first(value: Any, key: str) -> Any:
    if isinstance(value, Mapping):
        if key in value:
            return value[key]
        for item in value.values():
            found = _first(item, key)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _first(item, key)
            if found is not None:
                return found
    return None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _credit(value: Mapping[str, Any]) -> Any:
    for container, key in (
        (value.get("qualification"), "credit"),
        (value.get("authorization"), "credit"),
        (value.get("decision"), "credit"),
        (value.get("qualification"), "qualification_credit"),
        (value.get("decision"), "qualification_credit"),
    ):
        if isinstance(container, Mapping) and key in container:
            return container[key]
    return value.get("credit")


def _bind(root: Path, relative: Path, *, kind: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    path, raw = _read_bytes(
        root,
        relative,
        limit=MAX_JSON_BYTES if kind == "report" else MAX_SOURCE_BYTES,
    )
    digest = hashlib.sha256(raw).hexdigest()
    binding: dict[str, Any] = {
        "path": relative.as_posix(),
        "kind": kind,
        "bytes": len(raw),
        "sha256": digest,
        "content_read": True,
        "symlink": False,
    }
    payload: dict[str, Any] | None = None
    if kind == "report":
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)),
        )
        if not isinstance(payload, dict):
            raise TypeError(f"expected report object: {relative}")
        binding.update(
            {
                "schema": payload.get("schema"),
                "status": _status(payload),
                "credit": _credit(payload),
            }
        )
    return binding, payload


def _scope_observation(anchor: Mapping[str, Any]) -> dict[str, Any]:
    scope = anchor.get("scope") if isinstance(anchor.get("scope"), Mapping) else {}
    return {
        "family": scope.get("family"),
        "scope_id": scope.get("scope_id"),
        "case_id": scope.get("case_id"),
        "source_hdf5": scope.get("source_path"),
        "source_sha256": scope.get("source_sha256"),
    }


def _contract_snapshot(reports: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    root = reports["root_scheduler"]
    fresh = reports["fresh_root_scheduler"]
    external = reports["external_receipt"]
    host = reports["host_io"]
    terminal = reports["terminal_evidence"]
    sidecar = reports["case_sidecar"]
    matrix = reports["sidecar_matrix"]
    readiness = reports["readiness_projection"]
    anchor = reports["anchor"]

    root_auth = root.get("authorization", {})
    fresh_auth = fresh.get("authorization", {})
    external_auth = external.get("authorization", {})
    host_decision = host.get("decision", {})
    host_boundary = host.get("authorization_boundary", {})
    terminal_ref = terminal.get("fresh_attempt_contract", {}).get("terminal_evidence_ref", {})
    terminal_intake = terminal.get("terminal_evidence_intake", {})
    sidecar_intake = sidecar.get("case_sidecar_intake", {})
    sidecar_qualification = sidecar.get("qualification", {})
    matrix_qualification = matrix.get("qualification", {})
    readiness_matrix = readiness.get("sidecar_matrix", {})
    anchor_decision = anchor.get("decision", {})

    return {
        "anchor": {
            "status": _status(anchor),
            "T1": anchor_decision.get("T1"),
            "T2": anchor_decision.get("T2"),
            "T2_macro": anchor_decision.get("T2_macro"),
            "formal": anchor_decision.get("formal"),
            "promotion_allowed": anchor_decision.get("promotion_allowed"),
            "scheduler_spec_created": anchor_decision.get("scheduler_spec_created"),
            "credit": anchor_decision.get("credit"),
        },
        "root_scheduler": {
            "status": _status(root),
            "root_authorization_intake_bound": root_auth.get("root_authorization_intake_bound"),
            "scheduler_host_io_reservation_bound": root_auth.get("scheduler_host_io_reservation_bound"),
            "launch_admitted": root_auth.get("launch_admitted"),
            "worker_launch_authorized": root_auth.get("worker_launch_authorized"),
            "credit": root_auth.get("credit"),
            "receipt_paths": {
                name: {
                    "exists": item.get("exists", item.get("present")),
                    "path": item.get("path"),
                    "error": item.get("error"),
                }
                for name, item in root.get("receipt_observations", root.get("receipts", {})).items()
                if isinstance(item, Mapping)
            },
        },
        "fresh_root_scheduler": {
            "status": _status(fresh),
            "launch_allowed": fresh_auth.get("launch_allowed"),
            "formal": fresh_auth.get("formal"),
            "credit": fresh_auth.get("credit"),
            "fresh_root_exists": fresh.get("receipts", {}).get("fresh_root", {}).get("exists"),
            "scheduler_host_io_exists": fresh.get("receipts", {}).get("scheduler_host_io", {}).get("exists"),
        },
        "external_receipt": {
            "status": _status(external),
            "external_receipts_verified": external_auth.get("external_receipts_verified"),
            "launch_allowed": external_auth.get("launch_allowed"),
            "formal": external_auth.get("formal"),
            "credit": external_auth.get("credit"),
            "receipt_paths": {
                name: {
                    "exists": item.get("exists"),
                    "path": item.get("path"),
                    "error": item.get("error"),
                }
                for name, item in external.get("receipts", {}).items()
                if isinstance(item, Mapping)
            },
        },
        "host_io": {
            "status": _status(host),
            "root_authorization_present": host_decision.get("root_authorization_present"),
            "scheduler_authorization_present": host_decision.get("scheduler_authorization_present"),
            "launch_admitted": host_decision.get("launch_admitted"),
            "worker_launch_authorized": host_decision.get("worker_launch_authorized"),
            "probe_is_authorization": host_boundary.get("probe_is_authorization"),
            "credit": host_decision.get("credit"),
        },
        "terminal_evidence": {
            "status": _status(terminal),
            "sidecar_present": terminal_intake.get("present"),
            "sidecar_status": terminal_intake.get("status"),
            "sidecar_path": terminal_ref.get("path"),
            "sidecar_exists": terminal_ref.get("exists"),
            "event_window_complete": terminal.get("terminal_evidence", {}).get("event_window_complete", False),
            "blocking_reasons": terminal.get("blocking_reasons", []),
            "credit": terminal.get("qualification", {}).get("credit"),
        },
        "material_sidecar": {
            "status": _status(sidecar),
            "sidecar_present": sidecar_intake.get("present"),
            "sidecar_status": sidecar_intake.get("status"),
            "sidecar_blocking_reasons": sidecar_intake.get("blocking_reasons", []),
            "formal": sidecar_qualification.get("formal"),
            "T2": sidecar_qualification.get("T2"),
            "credit": sidecar_qualification.get("credit"),
        },
        "sidecar_matrix": {
            "status": _status(matrix),
            "formal": matrix_qualification.get("formal"),
            "T2": matrix_qualification.get("T2"),
            "credit": matrix_qualification.get("credit"),
            "matrix_ready": readiness_matrix.get("matrix_ready"),
            "expected_case_count": readiness_matrix.get("expected_case_count"),
            "missing_case_count": readiness_matrix.get("missing_case_count"),
            "formal_acceptance_receipt_count": readiness_matrix.get("formal_acceptance_receipt_count"),
        },
        "readiness": {
            "status": _status(readiness),
            "T2": readiness.get("T2"),
            "credit": readiness.get("credit"),
            "terminal_status": _mapping(readiness.get("terminal_evidence")).get("status"),
            "terminal_present": _mapping(readiness.get("terminal_evidence")).get("present"),
        },
    }


def _checks(snapshot: Mapping[str, Any]) -> dict[str, bool]:
    anchor = snapshot["anchor"]
    root = snapshot["root_scheduler"]
    fresh = snapshot["fresh_root_scheduler"]
    external = snapshot["external_receipt"]
    host = snapshot["host_io"]
    terminal = snapshot["terminal_evidence"]
    sidecar = snapshot["material_sidecar"]
    matrix = snapshot["sidecar_matrix"]
    readiness = snapshot["readiness"]
    return {
        "anchor_preserves_zero_credit": (
            anchor["status"] == "blocked_fail_closed"
            and anchor["T1"] is False
            and anchor["T2"] is False
            and anchor["T2_macro"] is False
            and anchor["formal"] is False
            and anchor["promotion_allowed"] is False
            and anchor["scheduler_spec_created"] is False
            and anchor["credit"] == 0
        ),
        "root_scheduler_missing_authority_fails_closed": (
            root["status"] == "blocked_missing_fresh_root_scheduler_receipts"
            and root["root_authorization_intake_bound"] is False
            and root["scheduler_host_io_reservation_bound"] is False
            and root["launch_admitted"] is False
            and root["worker_launch_authorized"] is False
            and root["credit"] == 0
            and all(item.get("exists") is False for item in root["receipt_paths"].values())
        ),
        "fresh_root_scheduler_contract_is_non_authorizing": (
            fresh["status"] == "blocked_missing_fresh_root_scheduler_receipts"
            and fresh["launch_allowed"] is False
            and fresh["formal"] is False
            and fresh["credit"] == 0
            and fresh["fresh_root_exists"] is False
            and fresh["scheduler_host_io_exists"] is False
        ),
        "external_receipt_contract_is_non_authorizing": (
            external["status"] == "blocked_missing_external_receipts"
            and external["external_receipts_verified"] is False
            and external["launch_allowed"] is False
            and external["formal"] is False
            and external["credit"] == 0
            and all(item.get("exists") is False for item in external["receipt_paths"].values())
        ),
        "host_io_projection_cannot_authorize_launch": (
            host["status"] == "diagnostic_admission_blocked"
            and host["root_authorization_present"] is False
            and host["scheduler_authorization_present"] is False
            and host["launch_admitted"] is False
            and host["worker_launch_authorized"] is False
            and host["probe_is_authorization"] is False
            and host["credit"] == 0
        ),
        "terminal_evidence_missing_fails_closed": (
            terminal["status"] == "blocked_fail_closed"
            and terminal["sidecar_present"] is False
            and terminal["sidecar_status"] == "missing"
            and terminal["sidecar_exists"] is False
            and terminal["credit"] == 0
        ),
        "material_sidecar_missing_fails_closed": (
            sidecar["status"] == "blocked_fail_closed"
            and sidecar["sidecar_present"] is False
            and sidecar["sidecar_status"] == "missing"
            and sidecar["formal"] is False
            and sidecar["T2"] is False
            and sidecar["credit"] == 0
        ),
        "sidecar_matrix_is_not_qualified": (
            matrix["status"] == "blocked_fail_closed"
            and matrix["formal"] is False
            and matrix["T2"] is False
            and matrix["credit"] == 0
            and matrix["matrix_ready"] is False
            and matrix["expected_case_count"] == 32
            and matrix["missing_case_count"] == 32
            and matrix["formal_acceptance_receipt_count"] == 0
        ),
        "readiness_projection_remains_blocked": (
            readiness["status"] == "blocked_fail_closed"
            and readiness["T2"] is False
            and readiness["credit"] == 0
            and readiness["terminal_status"] == "missing"
            and readiness["terminal_present"] is False
        ),
    }


def build_report(root: Path = LAB_ROOT) -> dict[str, Any]:
    root = Path(root).resolve()
    bindings: dict[str, dict[str, Any]] = {}
    reports: dict[str, dict[str, Any]] = {}
    anchor_binding, anchor_payload = _bind(root, ANCHOR, kind="report")
    bindings["anchor"] = anchor_binding
    assert anchor_payload is not None
    reports["anchor"] = anchor_payload
    for name, path in REPORT_INPUTS.items():
        binding, payload = _bind(root, path, kind="report")
        bindings[name] = binding
        assert payload is not None
        reports[name] = payload
    for name, path in CODE_INPUTS.items():
        bindings[name], _ = _bind(root, path, kind="source")

    snapshot = _contract_snapshot(reports)
    checks = _checks(snapshot)
    return {
        "schema": SCHEMA,
        "artifact_class": "gap_report",
        "receipt_created": False,
        "observed_at_utc": OBSERVED_AT_UTC,
        "scope": {
            "family": FAMILY,
            "scope_id": SCOPE_ID,
            "case_id": CASE_ID,
            "source_hdf5": SOURCE_HDF5,
            "source_sha256": SOURCE_SHA256,
            "direction": "material_coarse_T2",
            "excluded_families": ["F3", "A8", "F8"],
        },
        "audit_basis": {
            "anchor_commit": "676a5286",
            "anchor_path": ANCHOR.as_posix(),
            "bounded_json_only": True,
            "trajectory_hdf5_opened": False,
            "trajectory_hdf5_hashed": False,
            "contracts_read": [*REPORT_INPUTS.keys(), *CODE_INPUTS.keys()],
        },
        "input_bindings": bindings,
        "contract_snapshot": snapshot,
        "contract_checks": checks,
        "finding": {
            "real_fail_closed_admission_vulnerability_found": False,
            "repair_applied": False,
            "code_mutation": False,
            "decision": "no_real_fail_closed_admission_vulnerability_found",
            "reason": (
                "Every inspected positive surface remains non-authorizing: missing root/scheduler "
                "authority, missing terminal evidence, missing case sidecar, source/reader drift, "
                "and an incomplete 32-case sidecar matrix all remain explicit blockers. A patch "
                "that would create or submit a spec would have to invent authority or alter a "
                "formal gate/denominator, so it is not a valid minimum repair."
            ),
            "candidate_paths_reviewed": [
                "promote_host_io_projection_to_launch_authority",
                "promote_historical_or_right_censored_terminal_diagnostic",
                "accept_sidecar_self_asserted_T1_T2_or_credit",
                "create_scheduler_spec_without_fresh_root_and_scheduler_receipts",
            ],
            "all_candidate_paths_rejected": True,
        },
        "blocking_gaps": [
            {
                "id": "F4-T2-RERUN3-GAP-ROOT-SCHEDULER-AUTHORITY",
                "status": "blocking",
                "evidence": "fresh root authorization and scheduler-owned host-I/O reservation are absent",
                "required_next_evidence": "producer-issued, cross-bound, one-use fresh-root and scheduler host-I/O receipts",
            },
            {
                "id": "F4-T2-RERUN3-GAP-TERMINAL-SIDECAR",
                "status": "blocking",
                "evidence": "fresh terminal evidence and the DEV_07 material case sidecar are missing",
                "required_next_evidence": "fresh namespace-bound terminal sidecar with complete event window, then read-only intake",
            },
            {
                "id": "F4-T2-RERUN3-GAP-SOURCE-MATRIX",
                "status": "blocking",
                "evidence": "archive/reader source drift remains unresolved and all 32 material sidecars are absent",
                "required_next_evidence": "authoritative archives-v2 collection/reader refresh and the complete 32-case sidecar matrix",
            },
        ],
        "spec_boundary": {
            "scheduler_spec_created": False,
            "submit_allowed": False,
            "reason": [
                "root authorization is absent",
                "scheduler-owned host-I/O reservation is absent",
                "fresh terminal evidence is absent",
                "material sidecar is absent",
                "sidecar matrix is 0/32 and formal acceptance receipts are 0",
                "source collection/reader drift is unresolved",
            ],
        },
        "execution_boundary": {
            "read_only_audit": True,
            "new_f4_paths_only": True,
            "receipt_files_created": False,
            "fresh_namespace_created": False,
            "scheduler_spec_created": False,
            "queue_submitted": False,
            "queue_started": False,
            "worker_started": False,
            "solver_started": False,
            "gpu_started": False,
            "registry_mutations": 0,
            "ledger_mutations": 0,
            "denominator_mutations": 0,
            "gate_mutations": 0,
            "completion_mutations": 0,
            "plan_mutations": 0,
            "update_411_mutations": 0,
            "history_rewritten": False,
            "new_paths": [
                DEFAULT_SCRIPT.as_posix(),
                DEFAULT_TEST.as_posix(),
                DEFAULT_JSON.as_posix(),
                DEFAULT_ZH.as_posix(),
            ],
        },
        "qualification": {
            "readiness_status": "blocked_fail_closed",
            "T1": False,
            "T2": False,
            "T2_macro": False,
            "formal": False,
            "qualification": False,
            "credit": 0,
        },
    }


def validate_report(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    required = {
        "schema", "artifact_class", "receipt_created", "observed_at_utc", "scope",
        "audit_basis", "input_bindings", "contract_snapshot", "contract_checks",
        "finding", "blocking_gaps", "spec_boundary", "execution_boundary", "qualification",
    }
    if set(report) != required:
        errors.append("top_level_fields")
    if report.get("schema") != SCHEMA:
        errors.append("schema")
    if report.get("artifact_class") != "gap_report" or report.get("receipt_created") is not False:
        errors.append("artifact_class")
    scope = report.get("scope", {})
    if not isinstance(scope, Mapping) or scope.get("family") != FAMILY or scope.get("case_id") != CASE_ID:
        errors.append("scope")
    if scope.get("source_hdf5") != SOURCE_HDF5 or scope.get("source_sha256") != SOURCE_SHA256:
        errors.append("source")
    if report.get("contract_checks") and not all(report["contract_checks"].values()):
        errors.append("contract_checks")
    finding = report.get("finding", {})
    if finding.get("real_fail_closed_admission_vulnerability_found") is not False:
        errors.append("finding.vulnerability")
    if finding.get("repair_applied") is not False or finding.get("code_mutation") is not False:
        errors.append("finding.mutation")
    spec = report.get("spec_boundary", {})
    if spec.get("scheduler_spec_created") is not False or spec.get("submit_allowed") is not False:
        errors.append("spec_boundary")
    qualification = report.get("qualification", {})
    if any(qualification.get(key) not in (False, 0, "blocked_fail_closed") for key in ("T1", "T2", "T2_macro", "formal", "qualification", "credit")):
        errors.append("qualification")
    execution = report.get("execution_boundary", {})
    for key in (
        "receipt_files_created", "fresh_namespace_created", "scheduler_spec_created",
        "queue_submitted", "queue_started", "worker_started", "solver_started", "gpu_started",
        "history_rewritten",
    ):
        if execution.get(key) is not False:
            errors.append(f"execution.{key}")
    for key in (
        "registry_mutations", "ledger_mutations", "denominator_mutations", "gate_mutations",
        "completion_mutations", "plan_mutations", "update_411_mutations",
    ):
        if execution.get(key) != 0:
            errors.append(f"execution.{key}")
    for name, binding in report.get("input_bindings", {}).items():
        path = binding.get("path", "")
        if any(token in path for token in ("F3", "A8", "F8")):
            errors.append(f"input_scope.{name}")
        if not isinstance(binding.get("sha256"), str) or len(binding["sha256"]) != 64:
            errors.append(f"input_hash.{name}")
    return sorted(set(errors))


def render_markdown(report: Mapping[str, Any]) -> str:
    snapshot = report["contract_snapshot"]
    checks = report["contract_checks"]
    lines = [
        "# F4 Tallwall120 material/T2 RERUN3 gap audit",
        "",
        "- 类型：`gap_report`（不是 receipt）",
        f"- 状态：`{report['qualification']['readiness_status']}`",
        f"- 锚定：`676a5286`",
        f"- scope：`{report['scope']['case_id']}`",
        "",
        "## 结论",
        "",
        "本轮没有发现可安全修补、且不改变正式 gate/分母/authority 的真实 fail-closed admission 漏洞。"
        "当前所有正向表面仍然是非授权合同；因此不创建或提交 scheduler spec。",
        "",
        "## 当前阻塞",
        "",
        f"- root/scheduler：`{snapshot['root_scheduler']['status']}`，两类 receipt 都不存在，launch/credit 均关闭。",
        f"- host-I/O：`{snapshot['host_io']['status']}`，root/scheduler authority 缺失，`launch_admitted=false`。",
        f"- terminal evidence：`{snapshot['terminal_evidence']['sidecar_status']}`，fresh sidecar 不存在。",
        f"- material sidecar：`{snapshot['material_sidecar']['sidecar_status']}`，T2/credit 均关闭。",
        f"- sidecar matrix：`{snapshot['sidecar_matrix']['missing_case_count']}/{snapshot['sidecar_matrix']['expected_case_count']}` cases missing，formal acceptance receipts=`{snapshot['sidecar_matrix']['formal_acceptance_receipt_count']}`。",
        "- archive/reader source drift 仍未解决；历史或 right-censored diagnostic 不可提升。",
        "",
        "## 合同检查",
        "",
    ]
    lines.extend(f"- `{name}`：`{value}`" for name, value in checks.items())
    lines.extend([
        "",
        "## 边界",
        "",
        "只读取有界 JSON/源码字节和已有文件元数据；没有打开或重哈希 trajectory HDF5，"
        "没有生成 receipt、namespace、spec，也没有启动 solver/worker/GPU/queue。"
        "没有修改 registry、ledger、denominator、gate、completion、PLAN 或 UPDATE-411。",
        "",
        "下一步必须先获得真实 producer-issued fresh-root 与 scheduler-owned host-I/O receipts，"
        "再完成 source/reader refresh、fresh terminal sidecar 和完整 32-case sidecar matrix；"
        "在此之前提交 spec 不被当前 contracts 允许。",
        "",
    ])
    return "\n".join(lines)


def write_outputs(report: Mapping[str, Any], output: Path = DEFAULT_JSON, zh_output: Path = DEFAULT_ZH) -> None:
    output = Path(output)
    zh_output = Path(zh_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    zh_output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    zh_output.write_text(render_markdown(report), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, default=LAB_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--zh-output", type=Path, default=DEFAULT_ZH)
    args = parser.parse_args(argv)
    report = build_report(args.lab_root)
    errors = validate_report(report)
    if errors:
        raise SystemExit("self-validation failed: " + ", ".join(errors))
    write_outputs(report, args.output, args.zh_output)
    print(json.dumps({"schema": SCHEMA, "status": report["qualification"]["readiness_status"], "credit": 0, "checks": len(report["contract_checks"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
