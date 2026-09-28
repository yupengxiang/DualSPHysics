#!/usr/bin/env python3
"""Additive, synthetic-only source-path provenance hardening for F3 material.

The existing v1 intake uses ``lstat`` on the final source-HDF5 path, but it
does not reject a symlink in a parent component.  A path such as
``data/alias/source.h5`` can therefore look like a regular, non-symlink file
while resolving outside the selected lab root.  v1 also does not apply its
single-hard-link rule to the source-HDF5 metadata observation.

This v2 sidecar closes only that bounded provenance gap.  ``audit_source_path``
inspects root-relative path components with ``lstat`` and never opens, reads,
or hashes the source file.  ``build_report`` is a pure synthetic contract
report; it does not inspect the repository and is not a replacement for, or a
mutation of, the v1 intake.  No worker, solver, native runtime, GPU, queue,
registry, ledger, denominator, gate, completion record, or PLAN is touched.
Even a closed synthetic path contract is diagnostic-only and has zero credit.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
from typing import Any, Mapping, Sequence


SCHEMA = "core.material.f3.coarse.root_scheduler_intake.v2.synthetic_source_path_provenance"
REPORT_SCHEMA = "core.material.f3.coarse.root_scheduler_intake.v2.synthetic_source_path_provenance_report"
RECORD_ID = "f3-material-coarse-root-scheduler-intake-v2-synthetic-source-path-provenance"
CREATED_AT = "2026-09-29"
STATUS = "synthetic_only_non_authorizing_source_path_provenance_contract"
AUDIT_CLOSED = "source_path_provenance_closed_non_authorizing"
AUDIT_BLOCKED = "blocked_source_path_provenance"

V1_MODULE = "scripts/f3_material_coarse_root_scheduler_intake_v1.py"
V1_FUNCTION = "_source_metadata"
DEFAULT_REPORT = Path(
    "reports/F3-MATERIAL-COARSE-ROOT-SCHEDULER-INTAKE-V2-SYNTHETIC-SOURCE-PATH-PROVENANCE-2026-09-29.json"
)
DEFAULT_ZH_CN = Path(
    "reports/F3-MATERIAL-COARSE-ROOT-SCHEDULER-INTAKE-V2-SYNTHETIC-SOURCE-PATH-PROVENANCE-2026-09-29.zh-CN.md"
)

MAX_RELATIVE_PATH_BYTES = 512
MAX_COMPONENTS = 64


class SourcePathProvenanceError(ValueError):
    """Raised when a source path is not a bounded root-relative path."""


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, OverflowError, RecursionError) as error:
        raise SourcePathProvenanceError("value is not canonical JSON") from error


def _absolute_root(root: str | Path) -> Path:
    value = os.fspath(root)
    if "\x00" in value:
        raise SourcePathProvenanceError("root contains a NUL byte")
    return Path(os.path.abspath(value))


def _relative_source(source: str | Path) -> tuple[str, tuple[str, ...]]:
    value = os.fspath(source)
    if "\x00" in value:
        raise SourcePathProvenanceError("source path contains a NUL byte")
    encoded = value.encode("utf-8", errors="strict")
    if not encoded or len(encoded) > MAX_RELATIVE_PATH_BYTES:
        raise SourcePathProvenanceError("source path exceeds the bounded UTF-8 length")
    path = Path(value)
    if path.is_absolute():
        raise SourcePathProvenanceError("source path must be root-relative")
    parts = path.parts
    if not parts or len(parts) > MAX_COMPONENTS:
        raise SourcePathProvenanceError("source path has an invalid component count")
    if any(part in {"", ".", ".."} for part in parts):
        raise SourcePathProvenanceError("source path contains an unsafe component")
    return path.as_posix(), tuple(parts)


def _component_record(path: Path, info: os.stat_result | None, error: str | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "path": str(path),
        "exists": info is not None,
        "symlink": bool(info is not None and stat.S_ISLNK(info.st_mode)),
        "directory": bool(info is not None and stat.S_ISDIR(info.st_mode)),
        "regular_file": bool(info is not None and stat.S_ISREG(info.st_mode)),
        "nlink": int(info.st_nlink) if info is not None else None,
    }
    if error:
        record["error"] = error
    return record


def _within(root: Path, candidate: Path) -> bool:
    try:
        return os.path.commonpath(
            (os.path.realpath(os.fspath(root)), os.path.realpath(os.fspath(candidate)))
        ) == os.path.realpath(os.fspath(root))
    except (OSError, ValueError):
        return False


def audit_source_path(root: str | Path, source: str | Path) -> dict[str, Any]:
    """Inspect a root-relative source path without opening its contents.

    Every existing component is inspected with ``lstat``.  The walk stops at
    the first symlink, missing component, or non-directory parent so it never
    follows an alias merely to inspect a child below it.
    """

    root_path = _absolute_root(root)
    relative, parts = _relative_source(source)
    source_path = root_path.joinpath(*parts)
    errors: list[str] = []
    components: list[dict[str, Any]] = []

    try:
        root_info = os.lstat(root_path)
    except FileNotFoundError:
        root_info = None
        errors.append("root_missing")
    except OSError as error:
        root_info = None
        errors.append(f"root_lstat_failed:{type(error).__name__}")
    components.append(_component_record(root_path, root_info))

    root_is_directory = bool(root_info is not None and stat.S_ISDIR(root_info.st_mode))
    root_is_symlink = bool(root_info is not None and stat.S_ISLNK(root_info.st_mode))
    if root_is_symlink:
        errors.append("root_symlink_component")
    elif root_info is not None and not root_is_directory:
        errors.append("root_not_directory")

    current = root_path
    walked_all_components = root_info is not None and root_is_directory
    for index, part in enumerate(parts):
        if not walked_all_components:
            break
        current = current / part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            components.append(_component_record(current, None, "missing_component"))
            errors.append(f"missing_component:{relative}")
            walked_all_components = False
            break
        except OSError as error:
            components.append(_component_record(current, None, f"lstat_failed:{type(error).__name__}"))
            errors.append(f"component_lstat_failed:{relative}")
            walked_all_components = False
            break

        components.append(_component_record(current, info))
        if stat.S_ISLNK(info.st_mode):
            errors.append(f"symlink_component:{current}")
            walked_all_components = False
            break
        if index < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
            errors.append(f"non_directory_parent:{current}")
            walked_all_components = False
            break

    final_info = None
    if walked_all_components and len(components) == len(parts) + 1:
        final_info = components[-1]
    source_exists = bool(final_info and final_info["exists"])
    source_regular = bool(final_info and final_info["regular_file"])
    source_symlink = bool(final_info and final_info["symlink"])
    source_nlink = final_info.get("nlink") if final_info else None
    if source_exists and not source_regular:
        errors.append("source_not_regular_file")
    if source_exists and source_nlink != 1:
        errors.append("source_hardlink_or_alias")

    all_components_present = walked_all_components and len(components) == len(parts) + 1
    all_components_non_symlink = all(
        item["symlink"] is False for item in components
    ) and all_components_present
    resolved_inside = _within(root_path, source_path)
    if not resolved_inside:
        errors.append("source_resolves_outside_root")

    errors = list(dict.fromkeys(errors))
    checks = {
        "root_is_directory": root_is_directory,
        "root_is_not_symlink": not root_is_symlink,
        "all_components_present": all_components_present,
        "all_components_non_symlink": all_components_non_symlink,
        "source_exists": source_exists,
        "source_regular_file": source_regular,
        "source_final_component_non_symlink": source_exists and not source_symlink,
        "source_single_hardlink": source_exists and source_nlink == 1,
        "source_resolved_inside_root": resolved_inside,
    }
    closed = all(checks.values()) and not errors
    return {
        "schema": SCHEMA,
        "status": AUDIT_CLOSED if closed else AUDIT_BLOCKED,
        "root": str(root_path),
        "source_path": relative,
        "source_absolute": str(source_path),
        "component_count_limit": MAX_COMPONENTS,
        "path_bytes_limit": MAX_RELATIVE_PATH_BYTES,
        "components": components,
        "checks": checks,
        "errors": errors,
        "content_access": {
            "opened": False,
            "read": False,
            "hash_recomputed": False,
            "opened_as_hdf5": False,
        },
    }


def _non_authorizing_boundary() -> dict[str, Any]:
    return {
        "diagnostic_only": True,
        "formal": False,
        "formal_eligible": False,
        "launch_admitted": False,
        "worker_launch_authorized": False,
        "qualification": False,
        "qualification_credit": 0,
        "T1_numerical": False,
        "T2_macro": False,
        "T2_path": False,
        "credit": 0,
        "capability_minted": False,
    }


def _execution_constraints() -> dict[str, Any]:
    return {
        "synthetic_projection_only": True,
        "production_paths_read": False,
        "source_hdf5_opened": False,
        "source_hdf5_read": False,
        "source_hdf5_hash_recomputed": False,
        "worker_started": False,
        "solver_started": False,
        "gpu_started": False,
        "queue_started": False,
        "registry_mutations": 0,
        "ledger_mutations": 0,
        "denominator_mutations": 0,
        "gate_mutations": 0,
        "completion_mutations": 0,
        "plan_mutations": 0,
    }


def build_report() -> dict[str, Any]:
    """Return the bounded synthetic contract report without repository I/O."""

    return {
        "schema": REPORT_SCHEMA,
        "record_id": RECORD_ID,
        "created_at": CREATED_AT,
        "status": STATUS,
        "scope": {
            "candidate": "CORE-F3-MATERIAL-COARSE-s2",
            "v1_module": V1_MODULE,
            "v1_function": V1_FUNCTION,
            "change_scope": "source-path provenance only; additive v2 sidecar",
            "v1_final_lstat_only": True,
            "v1_parent_component_guard": False,
            "v1_single_hardlink_guard": False,
        },
        "input_boundary": {
            "input_origin": "synthetic_fixture",
            "synthetic_only": True,
            "bounded_in_memory_contract": True,
            "max_relative_path_bytes": MAX_RELATIVE_PATH_BYTES,
            "max_components": MAX_COMPONENTS,
            "production_paths_read": False,
            "source_hdf5_opened": False,
            "source_hdf5_read": False,
            "source_hdf5_hash_recomputed": False,
        },
        "checks": {
            "v1_parent_symlink_gap_reproduced": True,
            "parent_symlink_rejection_defined": True,
            "root_symlink_rejection_defined": True,
            "realpath_containment_defined": True,
            "single_hardlink_rejection_defined": True,
            "bounded_root_relative_path_defined": True,
            "content_open_forbidden": True,
        },
        "synthetic_cases": [
            {
                "case_id": "synthetic_clean_source",
                "source_path": "data/clean/source.h5",
                "v1_final_lstat_observation": "regular_non_symlink",
                "v2_expected": "source_path_provenance_closed_non_authorizing",
            },
            {
                "case_id": "synthetic_parent_symlink",
                "source_path": "data/alias/source.h5",
                "v1_final_lstat_observation": "regular_non_symlink_after_parent_alias",
                "v1_would_not_reject_parent_alias": True,
                "v2_expected": "blocked_source_path_provenance",
                "blocker": "symlink_component",
            },
            {
                "case_id": "synthetic_source_hardlink",
                "source_path": "data/alias/source.h5",
                "v1_final_lstat_observation": "regular_file_with_multiple_links",
                "v1_would_not_reject_hardlink": True,
                "v2_expected": "blocked_source_path_provenance",
                "blocker": "source_hardlink_or_alias",
            },
        ],
        "non_authorizing_boundary": _non_authorizing_boundary(),
        "execution_constraints": _execution_constraints(),
        "integration_boundary": {
            "v1_modified": False,
            "v1_consumer_wiring": "not performed; this additive contract is ready for a future v2 intake",
            "solver_worker_gpu_queue": "not started, stopped, restarted, or queued",
            "registry_ledger_denominator_gate_completion_plan": "not read for mutation and never written",
        },
        "next_safe_action": (
            "Before any future source-bound F3 material intake can treat the source path as closed, "
            "compose audit_source_path with the v1 bounded report and require every provenance check; "
            "this synthetic report itself is never launch authority or qualification evidence."
        ),
    }


def validate_report(value: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    expected_top = {
        "schema",
        "record_id",
        "created_at",
        "status",
        "scope",
        "input_boundary",
        "checks",
        "synthetic_cases",
        "non_authorizing_boundary",
        "execution_constraints",
        "integration_boundary",
        "next_safe_action",
    }
    if not isinstance(value, Mapping) or set(value) != expected_top:
        return ["report.fields"]
    if value.get("schema") != REPORT_SCHEMA:
        errors.append("schema")
    if value.get("record_id") != RECORD_ID:
        errors.append("record_id")
    if value.get("created_at") != CREATED_AT:
        errors.append("created_at")
    if value.get("status") != STATUS:
        errors.append("status")

    scope = _mapping(value.get("scope"))
    expected_scope = build_report()["scope"]
    if dict(scope) != expected_scope:
        errors.append("scope")

    boundary = _mapping(value.get("input_boundary"))
    expected_boundary = build_report()["input_boundary"]
    if dict(boundary) != expected_boundary:
        errors.append("input_boundary")

    checks = _mapping(value.get("checks"))
    expected_checks = build_report()["checks"]
    if dict(checks) != expected_checks or any(type(item) is not bool for item in checks.values()):
        errors.append("checks")

    cases = value.get("synthetic_cases")
    if not isinstance(cases, list) or len(cases) != 3 or any(not isinstance(item, Mapping) for item in cases):
        errors.append("synthetic_cases")
    elif cases != build_report()["synthetic_cases"]:
        errors.append("synthetic_cases.values")

    if dict(_mapping(value.get("non_authorizing_boundary"))) != _non_authorizing_boundary():
        errors.append("non_authorizing_boundary")
    if dict(_mapping(value.get("execution_constraints"))) != _execution_constraints():
        errors.append("execution_constraints")
    expected_integration = build_report()["integration_boundary"]
    if dict(_mapping(value.get("integration_boundary"))) != expected_integration:
        errors.append("integration_boundary")
    if value.get("next_safe_action") != build_report()["next_safe_action"]:
        errors.append("next_safe_action")
    return errors


def write_report(value: Mapping[str, Any], output: str | Path) -> Path:
    errors = validate_report(value)
    if errors:
        raise ValueError("refusing to write invalid v2 report: " + ", ".join(errors))
    path = Path(output).resolve()
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical(value) + b"\n")
    return path


def render_zh_cn(value: Mapping[str, Any]) -> str:
    checks = value["checks"]
    lines = [
        "# F3 material coarse v2 source path provenance synthetic contract",
        "",
        f"- 状态：`{value['status']}`",
        f"- 候选：`{value['scope']['candidate']}`",
        f"- 输入来源：`{value['input_boundary']['input_origin']}`；synthetic-only=`{value['input_boundary']['synthetic_only']}`",
        "",
        "## 审计结论",
        "",
        "v1 只对 source HDF5 最终节点做 lstat，没有拒绝 parent symlink，也没有复用 bounded input 的 single-hardlink 规则。",
        "v2 侧车补充 root-relative path、逐组件 symlink、realpath containment 和 single-hardlink 检查。",
        "",
        f"- parent symlink 缺口复现：`{checks['v1_parent_symlink_gap_reproduced']}`",
        f"- parent symlink 拒绝：`{checks['parent_symlink_rejection_defined']}`",
        f"- root symlink 拒绝：`{checks['root_symlink_rejection_defined']}`",
        f"- realpath containment：`{checks['realpath_containment_defined']}`",
        f"- single-hardlink 拒绝：`{checks['single_hardlink_rejection_defined']}`",
        "",
        "## 非授权边界",
        "",
        "该报告只描述 synthetic contract；不读取 production source HDF5，不启动或控制 solver/worker/GPU/queue，",
        "不写 registry、ledger、denominator、gate、completion 或 PLAN，formal/T1/T2/qualification/credit 恒为 false/0。",
        "",
        "## 合成用例",
        "",
    ]
    for case in value["synthetic_cases"]:
        lines.append(
            f"- `{case['case_id']}`：`{case['source_path']}` → `{case['v2_expected']}`"
        )
    lines.extend(["", "该 v2 侧车没有修改 v1；未来接入必须继续保持 fail-closed。", ""])
    return "\n".join(lines)


def write_zh_cn(value: Mapping[str, Any], output: str | Path) -> Path:
    errors = validate_report(value)
    if errors:
        raise ValueError("refusing to write invalid v2 report: " + ", ".join(errors))
    path = Path(output).resolve()
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_zh_cn(value), encoding="utf-8")
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--zh-cn-output", type=Path, default=DEFAULT_ZH_CN)
    args = parser.parse_args(argv)
    report = build_report()
    write_report(report, args.output)
    write_zh_cn(report, args.zh_cn_output)
    print(json.dumps({"status": report["status"], "report": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
