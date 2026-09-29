#!/usr/bin/env python3
"""Bind one F4 Tallwall120 CPU diagnostic to the current safe entry boundary.

This is a read-only intake/readiness artifact, not a receipt and not a
launcher.  It selects the existing DEV_07 material diagnostic as the
representative input, binds the current RERUN3 gap audit, and inspects the
current ``core_runtime`` and F4 sidecar entry points.  Missing fresh-root,
scheduler-owned host-I/O, terminal, and sidecar prerequisites stop execution
before any HDF5 content is opened.  The module never creates a namespace,
starts a solver/worker/native/GPU/queue process, or mutates formal state.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

if __package__ in {None, ""}:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import f4_tallwall120_material_case_sidecar_intake_v1 as sidecar_intake
from scripts import f4_tallwall120_material_coarse_t2_rerun3_gap_audit_v1 as gap_audit


LAB_ROOT = Path(__file__).resolve().parents[1]
OBSERVED_AT_UTC = "2026-09-29T00:00:00Z"
SCHEMA = "core.material.f4.tallwall120.cpu_diagnostic_intake.v1"
RECORD_ID = "f4-tallwall120-material-cpu-diagnostic-intake-v1"
STATUS_BLOCKED = "blocked_before_execution"

FAMILY = "F4"
SCOPE_ID = "F4_resting_pool_laminar_tallwall120_x_v1"
CASE_ID = f"{SCOPE_ID}_DEV_07"
SOURCE_HDF5 = gap_audit.SOURCE_HDF5
SOURCE_SHA256 = gap_audit.SOURCE_SHA256
SOURCE_BYTES = 2_067_911_708

GAP_REPORT = Path(
    "reports/F4-TALLWALL120-MATERIAL-COARSE-T2-RERUN3-GAP-2026-09-29.json"
)
EXISTING_DIAGNOSTIC = Path(
    "reports/F4-TALLWALL120-DEV07-MATERIAL-BASELINE24-DIAGNOSTIC-2026-09-28.json"
)
CORE_RUNTIME = Path("scripts/core_runtime.py")
MATERIAL_ENTRY = Path("scripts/f4_tallwall120_material.py")
SIDECAR_ENTRY = Path("scripts/f4_tallwall120_material_case_sidecar_intake_v1.py")
TERMINAL_ENTRY = Path("scripts/f4_tallwall120_material_terminal_evidence_intake_v1.py")

DEFAULT_JSON = Path(
    "reports/F4-TALLWALL120-MATERIAL-CPU-DIAGNOSTIC-INTAKE-2026-09-29-RERUN1.json"
)
DEFAULT_ZH_CN = Path(
    "reports/F4-TALLWALL120-MATERIAL-CPU-DIAGNOSTIC-INTAKE-2026-09-29-RERUN1.zh-CN.md"
)

MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_SOURCE_BYTES = 2 * 1024 * 1024
SHA256_LENGTH = 64


def _resolve(root: Path, relative: str | Path) -> Path:
    value = Path(relative)
    if value.is_absolute():
        raise ValueError(f"absolute input is outside the F4 intake set: {value}")
    path = (root / value).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError(f"input escapes lab root: {relative}") from error
    return path


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _parse_json(raw: bytes) -> dict[str, Any]:
    value = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
    )
    if not isinstance(value, dict):
        raise TypeError("expected a JSON object")
    return value


def _bounded_json(root: Path, relative: str | Path, *, role: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _resolve(root, relative)
    reference: dict[str, Any] = {
        "role": role,
        "path": Path(relative).as_posix(),
        "exists": path.is_file() and not path.is_symlink(),
        "bytes": None,
        "sha256": None,
        "content_read": False,
    }
    if not reference["exists"]:
        reference["error"] = "missing_or_symlink"
        return {}, reference
    size = path.stat().st_size
    reference["bytes"] = size
    if size > MAX_JSON_BYTES:
        reference["error"] = "file_exceeds_bounded_limit"
        return {}, reference
    raw = path.read_bytes()
    reference["sha256"] = hashlib.sha256(raw).hexdigest()
    reference["content_read"] = True
    return _parse_json(raw), reference


def _bounded_source(root: Path, relative: str | Path, *, role: str) -> tuple[str, dict[str, Any]]:
    path = _resolve(root, relative)
    reference: dict[str, Any] = {
        "role": role,
        "path": Path(relative).as_posix(),
        "exists": path.is_file() and not path.is_symlink(),
        "bytes": None,
        "sha256": None,
        "content_read": False,
    }
    if not reference["exists"]:
        reference["error"] = "missing_or_symlink"
        return "", reference
    size = path.stat().st_size
    reference["bytes"] = size
    if size > MAX_SOURCE_BYTES:
        reference["error"] = "file_exceeds_bounded_limit"
        return "", reference
    raw = path.read_bytes()
    reference["sha256"] = hashlib.sha256(raw).hexdigest()
    reference["content_read"] = True
    return raw.decode("utf-8"), reference


def _hdf5_metadata(root: Path) -> dict[str, Any]:
    """Stat the selected production input without opening or hashing content."""

    path = _resolve(root, SOURCE_HDF5)
    exists = path.is_file() and not path.is_symlink()
    return {
        "path": SOURCE_HDF5,
        "exists": exists,
        "regular_file": exists,
        "bytes": path.stat().st_size if exists else None,
        "declared_bytes": SOURCE_BYTES,
        "declared_sha256": SOURCE_SHA256,
        "content_opened": False,
        "content_read": False,
        "hash_recomputed": False,
        "metadata_contract_valid": exists and path.stat().st_size == SOURCE_BYTES,
    }


def _entry_contract(root: Path, relative: Path, *, role: str, required: Sequence[str], markers: Sequence[str]) -> dict[str, Any]:
    source, reference = _bounded_source(root, relative, role=role)
    functions: set[str] = set()
    parsed = False
    error: str | None = None
    if source:
        try:
            tree = ast.parse(source, filename=str(_resolve(root, relative)))
            functions = {
                node.name
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            parsed = True
        except (SyntaxError, UnicodeDecodeError) as exc:
            error = f"{type(exc).__name__}:{exc}"
    entrypoints = {name: name in functions for name in required}
    marker_checks = {marker: marker in source for marker in markers}
    checks = {
        "bounded_source_read": reference.get("content_read") is True,
        "ast_parse": parsed,
        "entrypoints": all(entrypoints.values()),
        "markers": all(marker_checks.values()),
    }
    result: dict[str, Any] = {
        "reference": reference,
        "entrypoints": entrypoints,
        "markers": marker_checks,
        "checks": checks,
    }
    if error is not None:
        result["error"] = error
    return result


def _diagnostic_observation(payload: Mapping[str, Any], reference: Mapping[str, Any]) -> dict[str, Any]:
    source = payload.get("source") if isinstance(payload.get("source"), Mapping) else {}
    parameters = payload.get("parameters") if isinstance(payload.get("parameters"), Mapping) else {}
    trace = payload.get("trace") if isinstance(payload.get("trace"), Mapping) else {}
    decision = payload.get("decision") if isinstance(payload.get("decision"), Mapping) else {}
    checks = {
        "report_readable": reference.get("content_read") is True,
        "schema": payload.get("schema") == "core.f4.tallwall120.material_diagnostic_receipt.v1",
        "case_identity": source.get("case_identity", {}).get("case_id") == CASE_ID
        if isinstance(source.get("case_identity"), Mapping)
        else False,
        "source_identity": source.get("repo_relative_path") == SOURCE_HDF5
        and source.get("before", {}).get("sha256") == SOURCE_SHA256
        if isinstance(source.get("before"), Mapping)
        else False,
        "diagnostic_only": payload.get("diagnostic_only") is True,
        "parameter_binding": parameters.get("q") == 0.5
        and parameters.get("dp_m") == 0.0075
        and parameters.get("seeds") == 512
        and parameters.get("substeps") == 2
        and parameters.get("neighbour_variant") == "baseline24",
        "event_window_complete": trace.get("event_window_complete") is True,
        "unknown_gate": trace.get("unknown_gate_pass") is True,
        "reliable_coverage": trace.get("common_reliable_path_coverage") == 1.0,
        "formal_admission_closed": decision.get("formal_admission") is False
        and decision.get("T1") is False
        and decision.get("T2") is False
        and decision.get("credit") == 0,
    }
    return {
        "reference": dict(reference),
        "status": payload.get("status"),
        "parameters": {
            key: parameters.get(key)
            for key in ("q", "dp_m", "seeds", "substeps", "neighbour_variant", "neighbours")
        },
        "trace": {
            key: trace.get(key)
            for key in (
                "status", "committed_frame", "frame_count", "transition_count",
                "event_window_complete", "event_window_status", "unknown_fraction_max",
                "unknown_gate_pass", "common_reliable_path_coverage", "mass_closed",
            )
        },
        "decision": {
            key: decision.get(key)
            for key in ("classification", "T1", "T2", "credit", "formal_admission")
        },
        "checks": checks,
        "historical_negative_only": True,
        "fresh_attempt": False,
        "may_authorize_execution": False,
    }


def _blocking_projection(gap: Mapping[str, Any], sidecar: Mapping[str, Any]) -> dict[str, Any]:
    snapshot = gap.get("contract_snapshot", {})
    root = snapshot.get("root_scheduler", {})
    fresh = snapshot.get("fresh_root_scheduler", {})
    host = snapshot.get("host_io", {})
    terminal = snapshot.get("terminal_evidence", {})
    material = snapshot.get("material_sidecar", {})
    matrix = snapshot.get("sidecar_matrix", {})
    sidecar_result = sidecar.get("case_sidecar_intake", {})
    return {
        "fresh_root": {
            "present": fresh.get("fresh_root_exists") is True,
            "valid": fresh.get("launch_allowed") is True,
            "launch_allowed": fresh.get("launch_allowed"),
        },
        "scheduler_host_io": {
            "present": fresh.get("scheduler_host_io_exists") is True,
            "valid": host.get("scheduler_authorization_present") is True,
            "launch_admitted": host.get("launch_admitted"),
            "worker_launch_authorized": host.get("worker_launch_authorized"),
        },
        "root_scheduler": {
            "status": root.get("status"),
            "launch_admitted": root.get("launch_admitted"),
            "worker_launch_authorized": root.get("worker_launch_authorized"),
        },
        "terminal": {
            "present": terminal.get("sidecar_present"),
            "event_window_complete": terminal.get("event_window_complete"),
            "status": terminal.get("status"),
        },
        "material_sidecar": {
            "present": material.get("sidecar_present"),
            "status": material.get("sidecar_status"),
            "credit": material.get("credit"),
        },
        "sidecar_intake": {
            "status": sidecar_result.get("status"),
            "present": sidecar_result.get("present"),
            "blocking_reasons": list(sidecar_result.get("blocking_reasons", [])),
        },
        "sidecar_matrix": {
            "expected_case_count": matrix.get("expected_case_count"),
            "missing_case_count": matrix.get("missing_case_count"),
            "formal_acceptance_receipt_count": matrix.get("formal_acceptance_receipt_count"),
            "matrix_ready": matrix.get("matrix_ready"),
        },
        "gap_ids": [item.get("id") for item in gap.get("blocking_gaps", [])],
        "gap_evidence": [
            {"id": item.get("id"), "evidence": item.get("evidence"), "required_next_evidence": item.get("required_next_evidence")}
            for item in gap.get("blocking_gaps", [])
        ],
    }


def build_report(root: str | Path = LAB_ROOT) -> dict[str, Any]:
    root_path = Path(os.path.abspath(os.fspath(root)))
    gap = gap_audit.build_report(root_path)
    gap_errors = gap_audit.validate_report(gap)
    gap_payload, gap_ref = _bounded_json(root_path, GAP_REPORT, role="current F4 RERUN3 gap audit")
    diagnostic_payload, diagnostic_ref = _bounded_json(
        root_path, EXISTING_DIAGNOSTIC, role="existing DEV_07 material diagnostic"
    )
    sidecar = sidecar_intake.build_report(root_path)
    runtime = _entry_contract(
        root_path,
        CORE_RUNTIME,
        role="current scheduler-owned core_runtime",
        required=("validate_scheduler_binding", "consume_scheduler_reservation", "worker", "prepare_launch", "launch"),
        markers=("SCHEDULER_BINDING_SCHEMA", "RESERVATION_CONSUME_SCHEMA", "check_runtime_identity=True"),
    )
    material = _entry_contract(
        root_path,
        MATERIAL_ENTRY,
        role="F4 CPU material diagnostic entry",
        required=("trace_tallwall120", "main"),
        markers=("h5py.File", "--source", "--output", "--seeds", "--substeps"),
    )
    sidecar_entry = _entry_contract(
        root_path,
        SIDECAR_ENTRY,
        role="F4 material case-sidecar intake entry",
        required=("evaluate_sidecar", "build_report", "validate_report", "main"),
        markers=("diagnostic_only", "credit", "hdf5_content_outside_bounded_json_boundary"),
    )
    terminal_entry = _entry_contract(
        root_path,
        TERMINAL_ENTRY,
        role="F4 terminal evidence intake entry",
        required=("build_report", "write_outputs", "main"),
        markers=("HDF5 content is outside the intake boundary", "terminal evidence", "credit"),
    )
    source = _hdf5_metadata(root_path)
    observation = _diagnostic_observation(diagnostic_payload, diagnostic_ref)
    blockers = _blocking_projection(gap, sidecar)
    prerequisite_checks = {
        "gap_report_current_and_valid": not gap_errors and gap_payload == gap,
        "selected_json_input_readable": observation["checks"]["report_readable"],
        "selected_input_case_bound": observation["checks"]["case_identity"] and observation["checks"]["source_identity"],
        "core_runtime_entry_contract_valid": all(runtime["checks"].values()),
        "material_entry_contract_valid": all(material["checks"].values()),
        "sidecar_entry_contract_valid": all(sidecar_entry["checks"].values()),
        "terminal_entry_contract_valid": all(terminal_entry["checks"].values()),
        "source_metadata_only_valid": source["metadata_contract_valid"] is True,
        "fresh_root_receipt_present": blockers["fresh_root"]["present"],
        "scheduler_host_io_receipt_present": blockers["scheduler_host_io"]["present"],
        "terminal_sidecar_present": blockers["terminal"]["present"],
        "material_case_sidecar_present": blockers["material_sidecar"]["present"],
        "sidecar_matrix_complete": blockers["sidecar_matrix"]["missing_case_count"] == 0,
        "launch_admitted": blockers["root_scheduler"]["launch_admitted"] is True,
    }
    blocking_reasons = [
        "fresh_root_receipt_missing_or_invalid",
        "scheduler_owned_host_io_reservation_missing_or_invalid",
        "fresh_terminal_evidence_missing_or_incomplete",
        "DEV_07_material_case_sidecar_missing",
        "material_sidecar_matrix_incomplete",
        "archive_reader_source_identity_drift",
    ]
    checks = {
        **prerequisite_checks,
        "all_execution_prerequisites_closed": all(
            prerequisite_checks[name]
            for name in (
                "fresh_root_receipt_present",
                "scheduler_host_io_receipt_present",
                "terminal_sidecar_present",
                "material_case_sidecar_present",
                "sidecar_matrix_complete",
                "launch_admitted",
            )
        ),
        "blocker_projection_nonempty": bool(blocking_reasons),
    }
    return {
        "schema": SCHEMA,
        "record_id": RECORD_ID,
        "artifact_class": "diagnostic_intake_readiness",
        "receipt_created": False,
        "observed_at_utc": OBSERVED_AT_UTC,
        "status": STATUS_BLOCKED,
        "scope": {
            "family": FAMILY,
            "scope_id": SCOPE_ID,
            "case_id": CASE_ID,
            "representative_case": "DEV_07",
            "direction": "material_coarse_T2",
            "excluded_families": ["F1", "F2", "F3", "F6", "F7", "F8", "A8"],
        },
        "selected_input": {
            "kind": "existing_negative_diagnostic_plus_source_metadata",
            "diagnostic": observation,
            "source_hdf5": source,
            "selection_reason": "DEV_07 is the current F4 material/T2 RERUN3 representative case and has a bounded readable diagnostic JSON; its HDF5 remains metadata-only until trusted fresh execution authority exists.",
        },
        "current_gap_binding": {
            "report": gap_ref,
            "schema": gap.get("schema"),
            "status": gap.get("qualification", {}).get("readiness_status"),
            "blocking": blockers,
            "gap_errors": gap_errors,
        },
        "runtime_entry_binding": {
            "core_runtime": runtime,
            "material_entry": material,
            "case_sidecar_entry": sidecar_entry,
            "terminal_evidence_entry": terminal_entry,
            "controlled_flow": "fresh root receipt + scheduler host-I/O reservation -> core_runtime one-shot validation -> F4 material CPU entry -> read-only sidecar intake",
            "entry_is_authorizing": False,
        },
        "planned_diagnostic": {
            "mode": "CPU-only",
            "q": 0.5,
            "dp_m": 0.0075,
            "seeds": 512,
            "substeps": 2,
            "neighbour_variant": "baseline24",
            "expected_output": "fresh namespace-bound material.h5 plus terminal material_case_sidecar.json",
            "executed": False,
            "execution_reason": "pre-execution fresh-root/host-I/O/terminal prerequisites are blocking",
        },
        "checks": checks,
        "blocking_reasons": blocking_reasons,
        "authorization": {
            "diagnostic_only": True,
            "formal": False,
            "formal_eligible": False,
            "qualification": False,
            "T1": False,
            "T2": False,
            "T2_macro": False,
            "launch_admitted": False,
            "worker_launch_authorized": False,
            "credit": 0,
        },
        "execution_boundary": {
            "diagnostic_executed": False,
            "runner_invoked": False,
            "source_hdf5_opened": False,
            "source_hdf5_read": False,
            "source_hdf5_hash_recomputed": False,
            "fresh_namespace_created": False,
            "material_sidecar_written": False,
            "terminal_receipt_created": False,
            "solver_started": False,
            "worker_started": False,
            "native_started": False,
            "gpu_started": False,
            "queue_started": False,
            "registry_mutations": 0,
            "ledger_mutations": 0,
            "denominator_mutations": 0,
            "gate_mutations": 0,
            "completion_mutations": 0,
            "plan_mutations": 0,
            "history_rewritten": False,
        },
        "next_safe_action": "仅在外部 producer 提供当前 source-bound、one-use fresh-root receipt 与 scheduler-owned host-I/O reservation，且 terminal event window/DEV_07 sidecar/source-reader identity 完整后，重新运行 intake；随后才可由受控入口执行 CPU-only diagnostic。",
    }


def validate_report(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    required = {
        "schema", "record_id", "artifact_class", "receipt_created", "observed_at_utc", "status",
        "scope", "selected_input", "current_gap_binding", "runtime_entry_binding", "planned_diagnostic",
        "checks", "blocking_reasons", "authorization", "execution_boundary", "next_safe_action",
    }
    if set(report) != required:
        return ["top_level_fields"]
    if report.get("schema") != SCHEMA or report.get("record_id") != RECORD_ID:
        errors.append("identity")
    if report.get("artifact_class") != "diagnostic_intake_readiness" or report.get("receipt_created") is not False:
        errors.append("artifact_class")
    if report.get("status") != STATUS_BLOCKED:
        errors.append("status")
    scope = report.get("scope", {})
    if not isinstance(scope, Mapping) or scope.get("family") != FAMILY or scope.get("case_id") != CASE_ID:
        errors.append("scope")
    selected = report.get("selected_input", {})
    diagnostic = selected.get("diagnostic", {}) if isinstance(selected, Mapping) else {}
    diagnostic_checks = diagnostic.get("checks", {}) if isinstance(diagnostic, Mapping) else {}
    for key in ("report_readable", "case_identity", "source_identity", "diagnostic_only", "formal_admission_closed"):
        if diagnostic_checks.get(key) is not True:
            errors.append(f"selected_input.diagnostic.{key}")
    source = selected.get("source_hdf5", {}) if isinstance(selected, Mapping) else {}
    if source.get("path") != SOURCE_HDF5 or source.get("declared_sha256") != SOURCE_SHA256 or source.get("declared_bytes") != SOURCE_BYTES:
        errors.append("selected_input.source")
    if source.get("content_opened") is not False or source.get("content_read") is not False or source.get("hash_recomputed") is not False:
        errors.append("selected_input.source_boundary")
    gap = report.get("current_gap_binding", {})
    if gap.get("status") != "blocked_fail_closed" or gap.get("gap_errors") != []:
        errors.append("gap_binding")
    if not isinstance(report.get("blocking_reasons"), list) or not report.get("blocking_reasons"):
        errors.append("blocking_reasons")
    checks = report.get("checks", {})
    if not isinstance(checks, Mapping) or checks.get("all_execution_prerequisites_closed") is not False or checks.get("blocker_projection_nonempty") is not True:
        errors.append("checks")
    runtime = report.get("runtime_entry_binding", {})
    if runtime.get("entry_is_authorizing") is not False:
        errors.append("runtime.authority")
    planned = report.get("planned_diagnostic", {})
    if planned.get("mode") != "CPU-only" or planned.get("executed") is not False:
        errors.append("planned_diagnostic")
    authorization = report.get("authorization", {})
    expected_auth = {
        "diagnostic_only": True, "formal": False, "formal_eligible": False, "qualification": False,
        "T1": False, "T2": False, "T2_macro": False, "launch_admitted": False,
        "worker_launch_authorized": False, "credit": 0,
    }
    if authorization != expected_auth:
        errors.append("authorization")
    execution = report.get("execution_boundary", {})
    false_fields = (
        "diagnostic_executed", "runner_invoked", "source_hdf5_opened", "source_hdf5_read",
        "source_hdf5_hash_recomputed", "fresh_namespace_created", "material_sidecar_written",
        "terminal_receipt_created", "solver_started", "worker_started", "native_started",
        "gpu_started", "queue_started", "history_rewritten",
    )
    for field in false_fields:
        if execution.get(field) is not False:
            errors.append(f"execution.{field}")
    for field in ("registry_mutations", "ledger_mutations", "denominator_mutations", "gate_mutations", "completion_mutations", "plan_mutations"):
        if execution.get(field) != 0:
            errors.append(f"execution.{field}")
    return sorted(set(errors))


def render_markdown(report: Mapping[str, Any]) -> str:
    selected = report["selected_input"]
    diagnostic = selected["diagnostic"]
    trace = diagnostic["trace"]
    blockers = report["current_gap_binding"]["blocking"]
    checks = report["checks"]
    lines = [
        "# F4 Tallwall120 material CPU diagnostic intake / readiness",
        "",
        "- 类型：`diagnostic_intake_readiness`（不是 receipt、不是 launch authorization）",
        f"- 状态：`{report['status']}`",
        f"- 代表案例：`{report['scope']['case_id']}`",
        "",
        "## 选择与结论",
        "",
        "选择 DEV_07 作为 F4 material/T2 RERUN3 的代表案例。已有 diagnostic JSON 可读，但只是历史 diagnostic-only 负结果：",
        f"`{trace.get('frame_count')} frames`、event window complete=`{trace.get('event_window_complete')}`、unknown fraction max=`{trace.get('unknown_fraction_max')}`、common reliable coverage=`{trace.get('common_reliable_path_coverage')}`。",
        "因此本轮在执行前被安全入口阻断，没有把历史结果伪造成 fresh receipt，也没有打开生产 HDF5 内容。",
        "",
        "## 当前 prerequisite",
        "",
        f"- fresh-root receipt：present=`{report['checks']['fresh_root_receipt_present']}`",
        f"- scheduler-owned host-I/O reservation：present=`{report['checks']['scheduler_host_io_receipt_present']}`",
        f"- fresh terminal / case sidecar：`{report['checks']['terminal_sidecar_present']}` / `{report['checks']['material_case_sidecar_present']}`",
        f"- sidecar matrix：missing=`{report['current_gap_binding']['blocking']['sidecar_matrix']['missing_case_count']}` / expected=`{report['current_gap_binding']['blocking']['sidecar_matrix']['expected_case_count']}`",
        f"- launch admitted：`{report['checks']['launch_admitted']}`",
        "",
        "## 入口绑定",
        "",
        "当前 `core_runtime`、F4 material CPU entry、case-sidecar intake 与 terminal-evidence intake 均做了有界源码绑定；这些入口本身不铸造 authority。",
        f"- core_runtime contract：`{report['checks']['core_runtime_entry_contract_valid']}`",
        f"- material entry contract：`{report['checks']['material_entry_contract_valid']}`",
        f"- sidecar entry contract：`{report['checks']['sidecar_entry_contract_valid']}`",
        f"- terminal entry contract：`{report['checks']['terminal_entry_contract_valid']}`",
        "",
        "## 阻塞原因",
        "",
    ]
    lines.extend(f"- `{item}`" for item in report["blocking_reasons"])
    lines.extend([
        "",
        "## 执行边界",
        "",
        "计划模式为 CPU-only、q=0.5、dp=0.0075、512 seeds、2 substeps、baseline24；由于 prerequisite 未闭合，`executed=false`。",
        "没有启动 solver/worker/native/GPU/queue，没有创建 fresh namespace 或写 material sidecar，没有改 registry/ledger/denominator/gate/completion/PLAN。",
        "",
        "## 下一步",
        "",
        report["next_safe_action"],
        "",
    ])
    return "\n".join(lines)


def write_outputs(report: Mapping[str, Any], output: str | Path, zh_cn_output: str | Path) -> None:
    errors = validate_report(report)
    if errors:
        raise ValueError("refusing to write invalid F4 CPU diagnostic intake: " + ", ".join(errors))
    json_path = Path(output).resolve()
    zh_path = Path(zh_cn_output).resolve()
    if json_path.exists() or zh_path.exists():
        raise FileExistsError("refusing to overwrite an existing F4 intake artifact")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    zh_path.parent.mkdir(parents=True, exist_ok=True)
    zh_path.write_text(render_markdown(report), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--zh-cn-output", type=Path, default=DEFAULT_ZH_CN)
    args = parser.parse_args(argv)
    report = build_report(args.root)
    write_outputs(report, args.output, args.zh_cn_output)
    print(json.dumps({"status": report["status"], "report": str(args.output)}, sort_keys=True))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
