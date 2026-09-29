#!/usr/bin/env python3
"""Validate the bounded F2 fallback boundary without authorizing execution.

This contract joins three already-recorded, small JSON projections:

* the static full-cup formal-readiness bridge;
* the dynamic DBC matrix/failure denominator; and
* the current pour/catch root-review audit.

It deliberately reads only a fixed JSON allow-list.  It never follows nested
artifact paths, opens production HDF5/BI4/trajectory data, invokes a solver,
or changes a registry, ledger, denominator, gate, completion record, queue,
GPU allocation, or PLAN.  The contract is useful precisely because it closes
the local boundary between these projections while preserving every external
blocker and returning zero formal/T1/T2/credit authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any, Mapping


LAB_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "core.f2.fallback_fail_closed_boundary_contract.v1"
REPORT_SCHEMA = "core.f2.fallback_fail_closed_boundary_contract_report.v1"
OBSERVED_AT_UTC = "2026-09-29T00:00:00Z"
MAX_JSON_BYTES = 256 * 1024

DEFAULT_OUTPUT = LAB_ROOT / (
    "campaigns/core-v1/cfd/f2-fallback-fail-closed-boundary-contract-v1.json"
)
DEFAULT_MARKDOWN_OUTPUT = LAB_ROOT / (
    "reports/F2-FALLBACK-FAIL-CLOSED-BOUNDARY-CONTRACT-V1-2026-09-29.zh-CN.md"
)

DEPENDENCY_PATHS: dict[str, Path] = {
    "static_full_cup_bridge": Path(
        "reports/F2-RESTING-FILL-FORMAL-RUN-READINESS-BRIDGE-V1-2026-09-28.json"
    ),
    "dynamic_matrix": Path(
        "campaigns/core-v1/cfd/f2-dynamic-third-family-dbc-duration-matrix-v1.json"
    ),
    "dynamic_failure_denominator": Path(
        "campaigns/core-v1/cfd/f2-dynamic-third-family-dbc-duration-failure-denominator-v1.json"
    ),
    "pour_catch_route": Path(
        "campaigns/core-v1/cfd/f2-pour-catch-route-audit-2026-09-29-RERUN1.json"
    ),
    "pour_catch_gap_audit": Path(
        "campaigns/core-v1/cfd/f2-pour-catch-root-review-gap-audit-v1-2026-09-29-RERUN1.json"
    ),
    "pour_catch_candidate": Path(
        "campaigns/core-v1/cfd/f2-pour-catch-candidate-card-v2-2026-09-29-RERUN1.json"
    ),
}

AUTHORIZATION = {
    "diagnostic_only": True,
    "formal": False,
    "formal_eligible": False,
    "T1": False,
    "T2": False,
    "T2_macro": False,
    "qualification": False,
    "formal_run_ready": False,
    "execution_authorized": False,
    "qualification_credit": 0,
    "credit": 0,
}

MUTATIONS = {
    "completion_mutation": 0,
    "denominator_mutation": 0,
    "gate_mutation": 0,
    "ledger_mutation": 0,
    "plan_mutation": 0,
    "queue_mutation": 0,
    "registry_mutation": 0,
}

READ_POLICY = {
    "fixed_json_allowlist_only": True,
    "max_json_bytes": MAX_JSON_BYTES,
    "nested_artifact_paths_followed": False,
    "production_hdf5_bi4_trajectory_opened": False,
    "production_artifact_stat_or_hash": False,
    "xml_or_native_input_opened": False,
    "solver_worker_native_gpu_queue_started": False,
    "registry_ledger_denominator_gate_completion_plan_written": False,
}

BLOCKER_CODES = (
    "cell_00_historical_hard_failure",
    "static_missing_runtime_rows",
    "dynamic_boundary_and_open_mouth_negative_evidence",
    "dynamic_event_window_not_complete",
    "catch_event_ownership_unreviewed",
    "catch_new_definition_and_preflight_missing",
)


class ContractError(ValueError):
    """Raised when a bounded F2 input or the contract itself drifts."""


def _fail(message: str) -> None:
    raise ContractError(f"fail-closed: {message}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_constant(token: str) -> Any:
    _fail(f"non-standard JSON constant is not allowed: {token}")


def _check_finite(value: Any, label: str) -> None:
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            _fail(f"{label} contains a non-finite number")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _check_finite(item, f"{label}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _check_finite(item, f"{label}[{index}]")


def _assert_no_symlink_components(path: Path) -> None:
    try:
        relative = path.relative_to(LAB_ROOT)
    except ValueError as error:
        raise ContractError(f"fail-closed: dependency escapes lab root: {path}") from error
    current = LAB_ROOT
    for component in relative.parts:
        current /= component
        try:
            info = os.lstat(current)
        except OSError as error:
            raise ContractError(f"fail-closed: cannot inspect dependency: {path}") from error
        if stat.S_ISLNK(info.st_mode):
            _fail(f"symlink dependency rejected: {path}")


def _read_bounded_json(relative: Path, *, role: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        _fail(f"non-canonical dependency path: {relative}")
    if relative.suffix.lower() != ".json":
        _fail(f"non-JSON dependency rejected: {relative}")
    path = (LAB_ROOT / relative).resolve(strict=False)
    _assert_no_symlink_components(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(os.fspath(path), flags)
    except OSError as error:
        raise ContractError(f"fail-closed: dependency unavailable: {relative}") from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            _fail(f"dependency is not a single-link regular file: {relative}")
        if before.st_size <= 0 or before.st_size > MAX_JSON_BYTES:
            _fail(f"dependency exceeds bounded size: {relative}")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                _fail(f"dependency was truncated while read: {relative}")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1) != b"":
            _fail(f"dependency grew while read: {relative}")
        after = os.fstat(descriptor)
        if (
            before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ino != after.st_ino
        ):
            _fail(f"dependency changed while read: {relative}")
    finally:
        os.close(descriptor)

    raw = b"".join(chunks)
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContractError(f"fail-closed: invalid JSON dependency: {relative}") from error
    if not isinstance(payload, dict):
        _fail(f"JSON object required: {relative}")
    _check_finite(payload, relative.as_posix())
    return payload, {
        "path": relative.as_posix(),
        "role": role,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "content_opened": True,
        "nested_artifact_paths_followed": False,
    }


def _require(condition: bool, message: str) -> None:
    if not condition:
        _fail(message)


def _all_zero(values: Mapping[str, Any], keys: tuple[str, ...]) -> bool:
    return all(values.get(key) == 0 for key in keys)


def _validate_current_evidence(
    static: Mapping[str, Any],
    dynamic_matrix: Mapping[str, Any],
    dynamic_denominator: Mapping[str, Any],
    catch_route: Mapping[str, Any],
    catch_gap: Mapping[str, Any],
    catch_candidate: Mapping[str, Any],
) -> dict[str, bool]:
    static_runtime = static.get("evidence", {}).get("runtime", {})
    static_rows = static_runtime.get("rows", [])
    static_row0 = static_rows[0] if static_rows else {}
    static_future = static.get("readiness", {}).get("future_formal_run", {})
    static_preparation = static.get("evidence", {}).get("preparation", {})

    dynamic_controls = dynamic_matrix.get("execution_controls", {})
    dynamic_cells = dynamic_matrix.get("cells", [])
    dynamic_denominator_matrix = dynamic_denominator.get("matrix", {})
    historical = {
        item.get("id"): item
        for item in dynamic_denominator.get("historical_evidence", [])
        if isinstance(item, Mapping)
    }
    mdbc_failure = historical.get("moving_mdbc_contact_failure", {})
    open_tray_failure = historical.get("open_tray_position_loss", {})
    preflight = historical.get("q0p75_cpu_anchor_preflight", {})

    catch_core = catch_route.get("core_gate", {})
    catch_selected = catch_route.get("selected_route", {})
    catch_execution = catch_route.get("execution_controls", {})
    catch_comparison = catch_route.get("route_comparison", {})
    catch_dynamic = catch_comparison.get("closed_dynamic_dbc", {})
    catch_selected_comparison = catch_comparison.get("selected_receiver_ballistic_v2", {})
    catch_gap_ids = {
        item.get("id")
        for item in catch_gap.get("gaps", [])
        if isinstance(item, Mapping)
    }
    catch_plan = catch_candidate.get("planned_matrix", {})
    catch_topology = catch_candidate.get("topology", {})

    checks = {
        "static_bridge_is_blocked": static.get("status") == "blocked_fail_closed",
        "static_cell_00_hard_failure": (
            static_runtime.get("registered_rows") == 15
            and static_runtime.get("historical_failed_rows") == 1
            and static_row0.get("index") == 0
            and static_row0.get("historical_runtime_status") == "failed_static_gate"
            and static_row0.get("formal_run_readiness") == "blocked_by_historical_failure"
            and "open_cup_escape" in static_row0.get("historical_failure_categories", [])
        ),
        "static_missing_runtime_rows": (
            static_runtime.get("missing_runtime_rows") == 14
            and static_runtime.get("historical_runtime_pass_rows") == 0
            and static_runtime.get("formal_evidence_complete") is False
            and static_future.get("formal_run_ready") is False
        ),
        "static_rows_zero_credit": (
            len(static_rows) == 15
            and all(
                row.get("T1_numerical") is False
                and row.get("T2") is False
                and row.get("credit") == 0
                for row in static_rows
            )
        ),
        "static_preparation_is_not_runtime": (
            static_preparation.get("prepared_cells") == 15
            and static_preparation.get("solver_invoked") is False
            and static_preparation.get("gpu_invoked") is False
            and static_preparation.get("jobs_materialized") is False
        ),
        "dynamic_matrix_is_unsubmitted": (
            dynamic_matrix.get("status") == "fixed_design_cpu_preflight_anchor_only"
            and dynamic_matrix.get("denominator") == 15
            and dynamic_matrix.get("numerator") == 0
            and len(dynamic_cells) == 15
            and all(cell.get("status") == "not_started" for cell in dynamic_cells)
            and dynamic_controls.get("materialized_cells") == 0
            and dynamic_controls.get("submitted_cells") == 0
            and dynamic_controls.get("solver_invoked_by_this_artifact") is False
            and dynamic_controls.get("gpu_invoked_by_this_artifact") is False
        ),
        "dynamic_boundary_and_open_mouth_negative_evidence": (
            dynamic_matrix.get("fixed_recipe", {}).get("boundary_method") == 1
            and "native DBC" in dynamic_matrix.get("fixed_recipe", {}).get("boundary_semantics", "")
            and "open top" in dynamic_matrix.get("fixed_recipe", {}).get("physical_geometry", "")
            and mdbc_failure.get("hard_integrity_pass") is False
            and mdbc_failure.get("native_exclusions") == 4
            and open_tray_failure.get("hard_integrity_pass") is False
            and open_tray_failure.get("native_missing_fluid_count", 0) > 0
        ),
        "dynamic_event_window_remains_blocked": (
            dynamic_denominator_matrix.get("fixed_denominator") == 15
            and dynamic_denominator_matrix.get("executed") == 0
            and dynamic_denominator_matrix.get("passed") == 0
            and dynamic_denominator_matrix.get("unattempted") == 15
            and dynamic_denominator_matrix.get("preflight_anchor_credit") == 0
            and "no horizon extension" in dynamic_denominator.get("rules", {}).get("event_censor", "")
            and "15/15" in dynamic_denominator.get("rules", {}).get("promotion", "")
            and preflight.get("solver_product_present") is False
        ),
        "catch_route_is_root_review_only": (
            catch_route.get("status") == "root_review_only_conditional_route"
            and catch_selected.get("qualification_claim") == "none"
            and catch_selected_comparison.get("worth_preflight_now") is False
            and catch_selected.get("same_input_retry") is False
            and catch_dynamic.get("event_window_complete") is False
            and catch_dynamic.get("credit") == 0
        ),
        "catch_event_ownership_unreviewed": (
            catch_gap.get("status") == "blocked_before_new_definition"
            and catch_gap.get("decision") == "hold_new_definition_until_root_gaps_are_closed"
            and {"EVENT_CONTRACT_UNREVIEWED", "CPU_NATIVE_PREFLIGHT_MISSING", "SECOND_ROOT_REVIEW_REQUIRED"}
            <= catch_gap_ids
            and catch_topology.get("receiver") == "fixed open-top basin with closed floor and side walls"
        ),
        "catch_matrix_is_proposal_only": (
            catch_plan.get("proposed_rows") == 15
            and catch_plan.get("proposal_only") is True
            and catch_plan.get("executed") == 0
            and catch_plan.get("unattempted") == 15
            and catch_plan.get("credit") == 0
            and catch_plan.get("parent_scope_denominator_unchanged") is True
            and catch_candidate.get("T1_numerical") is False
            and catch_candidate.get("qualification_claim") == "none"
        ),
        "no_catch_execution_authority": (
            catch_execution.get("read_only_audit") is True
            and catch_execution.get("definition_writer") is False
            and catch_execution.get("cpu_gencase") is False
            and catch_execution.get("native_decode") is False
            and catch_execution.get("solver") is False
            and catch_execution.get("gpu") is False
            and _all_zero(
                catch_execution,
                ("queue_mutation", "ledger_mutation", "registry_mutation", "T1_denominator_mutation", "T2_denominator_mutation"),
            )
        ),
        "core_gate_is_unchanged": (
            catch_core.get("registered_t1_families") == ["F3", "F4"]
            and catch_core.get("required_t1_family_count") == 3
            and catch_core.get("three_t1_families") is False
            and catch_core.get("qualification_credit_added") == 0
            and catch_core.get("registry_mutation") == 0
            and catch_core.get("ledger_mutation") == 0
            and catch_core.get("T1_denominator_mutation") == 0
            and catch_core.get("T2_denominator_mutation") == 0
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    _require(
        not failed,
        "one or more F2 source projections changed or were promoted: " + ", ".join(failed),
    )
    return checks


def _validate_authorization(value: Mapping[str, Any]) -> None:
    _require(dict(value) == AUTHORIZATION, "contract authorization is not exactly fail-closed")


def build_contract() -> dict[str, Any]:
    loaded: dict[str, dict[str, Any]] = {}
    dependencies: dict[str, dict[str, Any]] = {}
    roles = {
        "static_full_cup_bridge": "static/full-cup formal-readiness projection",
        "dynamic_matrix": "dynamic DBC fixed matrix projection",
        "dynamic_failure_denominator": "dynamic boundary/event failure denominator",
        "pour_catch_route": "pour/catch route decision projection",
        "pour_catch_gap_audit": "pour/catch root-review gap projection",
        "pour_catch_candidate": "pour/catch fresh candidate projection",
    }
    for name, relative in DEPENDENCY_PATHS.items():
        loaded[name], dependencies[name] = _read_bounded_json(relative, role=roles[name])

    checks = _validate_current_evidence(
        loaded["static_full_cup_bridge"],
        loaded["dynamic_matrix"],
        loaded["dynamic_failure_denominator"],
        loaded["pour_catch_route"],
        loaded["pour_catch_gap_audit"],
        loaded["pour_catch_candidate"],
    )
    report = {
        "schema": REPORT_SCHEMA,
        "contract_schema": SCHEMA,
        "contract_id": "F2_FALLBACK_FAIL_CLOSED_BOUNDARY_V1",
        "created_at": OBSERVED_AT_UTC,
        "status": "blocked_fail_closed",
        "decision": "close_local_f2_boundary_without_formal_or_execution_promotion",
        "scope": {
            "static_full_cup": "cell-00 failure plus fixed 15-row missing-runtime boundary",
            "dynamic_dbc": "native DBC/open-top finite envelope with boundary and event blockers retained",
            "pour_catch": "fresh stationary-receiver hypothesis remains root-review-only",
        },
        "blockers": [
            {"code": code, "severity": "high"} for code in BLOCKER_CODES
        ],
        "checks": checks,
        "evidence": {
            "static_full_cup": {
                "status": loaded["static_full_cup_bridge"]["status"],
                "registered_rows": loaded["static_full_cup_bridge"]["evidence"]["runtime"]["registered_rows"],
                "historical_failed_rows": loaded["static_full_cup_bridge"]["evidence"]["runtime"]["historical_failed_rows"],
                "missing_runtime_rows": loaded["static_full_cup_bridge"]["evidence"]["runtime"]["missing_runtime_rows"],
                "cell_00": {
                    "status": loaded["static_full_cup_bridge"]["evidence"]["runtime"]["rows"][0]["historical_runtime_status"],
                    "formal_run_readiness": loaded["static_full_cup_bridge"]["evidence"]["runtime"]["rows"][0]["formal_run_readiness"],
                    "failure_categories": loaded["static_full_cup_bridge"]["evidence"]["runtime"]["rows"][0]["historical_failure_categories"],
                },
            },
            "dynamic_dbc": {
                "status": loaded["dynamic_matrix"]["status"],
                "denominator": loaded["dynamic_matrix"]["denominator"],
                "numerator": loaded["dynamic_matrix"]["numerator"],
                "boundary_method": loaded["dynamic_matrix"]["fixed_recipe"]["boundary_method"],
                "boundary_semantics": loaded["dynamic_matrix"]["fixed_recipe"]["boundary_semantics"],
                "open_mouth_geometry": "open top" in loaded["dynamic_matrix"]["fixed_recipe"]["physical_geometry"],
                "moving_mdbc_contact_failure": {
                    "hard_integrity_pass": loaded["dynamic_failure_denominator"]["historical_evidence"][2]["hard_integrity_pass"],
                    "native_exclusions": loaded["dynamic_failure_denominator"]["historical_evidence"][2]["native_exclusions"],
                },
                "open_tray_position_loss": {
                    "hard_integrity_pass": loaded["dynamic_failure_denominator"]["historical_evidence"][3]["hard_integrity_pass"],
                    "native_missing_fluid_count": loaded["dynamic_failure_denominator"]["historical_evidence"][3]["native_missing_fluid_count"],
                },
                "event_censor_rule": loaded["dynamic_failure_denominator"]["rules"]["event_censor"],
            },
            "pour_catch": {
                "route_status": loaded["pour_catch_route"]["status"],
                "candidate_status": loaded["pour_catch_candidate"]["status"],
                "gap_status": loaded["pour_catch_gap_audit"]["status"],
                "worth_preflight_now": loaded["pour_catch_gap_audit"]["worth_preflight_now"],
                "event_contract_gap": "EVENT_CONTRACT_UNREVIEWED" in {
                    item["id"] for item in loaded["pour_catch_gap_audit"]["gaps"]
                },
                "proposal_rows": loaded["pour_catch_candidate"]["planned_matrix"]["proposed_rows"],
                "proposal_credit": loaded["pour_catch_candidate"]["planned_matrix"]["credit"],
            },
        },
        "authorization": dict(AUTHORIZATION),
        "mutations": dict(MUTATIONS),
        "read_policy": dict(READ_POLICY),
        "dependencies": dependencies,
    }
    validate_report(report)
    return report


def validate_report(report: Mapping[str, Any]) -> dict[str, Any]:
    _require(report.get("schema") == REPORT_SCHEMA, "report schema mismatch")
    _require(report.get("contract_schema") == SCHEMA, "contract schema mismatch")
    _require(report.get("status") == "blocked_fail_closed", "report status was promoted")
    _require(report.get("decision") == "close_local_f2_boundary_without_formal_or_execution_promotion", "decision drift")
    _validate_authorization(report.get("authorization", {}))
    _require(dict(report.get("mutations", {})) == MUTATIONS, "mutation controls changed")
    _require(dict(report.get("read_policy", {})) == READ_POLICY, "read policy changed")
    _require(
        list(report.get("blockers", [])) == [
            {"code": code, "severity": "high"} for code in BLOCKER_CODES
        ],
        "blocker list changed",
    )
    checks = report.get("checks", {})
    _require(set(checks) == set(_EXPECTED_CHECK_NAMES), "check set changed")
    _require(all(value is True for value in checks.values()), "a fail-closed check is false")
    evidence = report.get("evidence", {})
    _require(evidence.get("static_full_cup", {}).get("missing_runtime_rows") == 14, "missing-runtime boundary drift")
    _require(evidence.get("static_full_cup", {}).get("cell_00", {}).get("status") == "failed_static_gate", "cell-00 boundary drift")
    _require(evidence.get("dynamic_dbc", {}).get("numerator") == 0, "dynamic numerator promotion")
    _require(evidence.get("pour_catch", {}).get("proposal_credit") == 0, "catch proposal credit promotion")
    for name, dependency in report.get("dependencies", {}).items():
        _require(dependency.get("content_opened") is True, f"dependency metadata missing: {name}")
        _require(dependency.get("nested_artifact_paths_followed") is False, f"nested path policy drift: {name}")
        _require(0 < dependency.get("bytes", 0) <= MAX_JSON_BYTES, f"dependency size drift: {name}")
        digest = dependency.get("sha256", "")
        _require(isinstance(digest, str) and len(digest) == 64, f"dependency hash drift: {name}")
    return dict(report)


_EXPECTED_CHECK_NAMES = (
    "static_bridge_is_blocked",
    "static_cell_00_hard_failure",
    "static_missing_runtime_rows",
    "static_rows_zero_credit",
    "static_preparation_is_not_runtime",
    "dynamic_matrix_is_unsubmitted",
    "dynamic_boundary_and_open_mouth_negative_evidence",
    "dynamic_event_window_remains_blocked",
    "catch_route_is_root_review_only",
    "catch_event_ownership_unreviewed",
    "catch_matrix_is_proposal_only",
    "no_catch_execution_authority",
    "core_gate_is_unchanged",
)


def render_markdown(report: Mapping[str, Any]) -> str:
    static = report["evidence"]["static_full_cup"]
    dynamic = report["evidence"]["dynamic_dbc"]
    catch = report["evidence"]["pour_catch"]
    lines = [
        "# F2 fallback fail-closed boundary contract v1（2026-09-29）",
        "",
        "这是一个只读 bounded contract validator 的独立闭环。它把当前 F2 static/full-cup、dynamic DBC/open-top 与 pour/catch root-review 状态绑定起来，但不把任何准备、历史失败或 canary 变成 formal/T1/credit。",
        "",
        "## 结论",
        "",
        "- 状态：`blocked_fail_closed`；所有 13 个契约检查通过。",
        f"- static/full-cup：固定 {static['registered_rows']} 行，cell-00 保留 `{static['cell_00']['status']}`，missing runtime `{static['missing_runtime_rows']}` 行。",
        f"- dynamic DBC：分母/分子 `{dynamic['denominator']}/{dynamic['numerator']}`；Boundary={dynamic['boundary_method']}，几何保留 open top；mDBC contact 与 open-tray position-loss 负证据继续阻塞。",
        f"- pour/catch：route=`{catch['route_status']}`，gap=`{catch['gap_status']}`，`worth_preflight_now={str(catch['worth_preflight_now']).lower()}`，proposal credit=`{catch['proposal_credit']}`。",
        "- formal/T1/T2/qualification 均为 `false`，credit 为 `0`；没有 solver、worker、native、GPU、queue 或中央状态写入。",
        "",
        "## 保留的硬边界",
        "",
        "- cell-00 hard failure、14 个 missing runtime、dynamic boundary/open-mouth（open-tray）负证据以及 catch event ownership 未审查均不可被该 contract 绕过。",
        "- 不读取依赖 JSON 中记录的 trajectory/HDF5/BI4 路径；只读取固定 allow-list 内的有限 JSON。",
        "- 不修改 PLAN、registry、ledger、denominator、gate、completion；不启动任何 native/solver/worker/GPU/queue。",
        "",
        "## 依赖",
        "",
        "| key | path | bytes | sha256 |",
        "|---|---|---:|---|",
    ]
    for name, dependency in report["dependencies"].items():
        lines.append(
            f"| `{name}` | `{dependency['path']}` | {dependency['bytes']} | `{dependency['sha256']}` |"
        )
    lines.extend(
        [
            "",
            "契约文件：`campaigns/core-v1/cfd/f2-fallback-fail-closed-boundary-contract-v1.json`。",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_new(path: Path, content: str) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(content)


def write_outputs(report: Mapping[str, Any], output: Path, markdown_output: Path) -> None:
    validate_report(report)
    _write_new(
        Path(output),
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
    )
    try:
        _write_new(Path(markdown_output), render_markdown(report))
    except Exception:
        Path(output).unlink(missing_ok=True)
        raise


def verify() -> dict[str, Any]:
    return build_contract()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    args = parser.parse_args()
    report = build_contract()
    write_outputs(report, args.output, args.markdown_output)
    print(
        json.dumps(
            {
                "schema": REPORT_SCHEMA,
                "status": report["status"],
                "checks": len(report["checks"]),
                "formal": report["authorization"]["formal"],
                "T1": report["authorization"]["T1"],
                "credit": report["authorization"]["credit"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
