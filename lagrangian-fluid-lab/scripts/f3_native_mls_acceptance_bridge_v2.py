#!/usr/bin/env python3
"""Build a read-only F3 native-MLS source-closure reconciliation.

This is a new, fail-closed namespace.  It consumes immutable JSON receipts and
source text only; it never opens HDF5, starts a solver/GPU/queue, or mutates a
registry, ledger, matrix, denominator, or historical receipt.  The artifact
is an acceptance *bridge* and source reconciliation, not a qualification
collector: every claim remains ``none`` and credit remains numeric zero.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA = "core.material.f3.native_volume_mls.acceptance_bridge.v2"
RECEIPT_SCHEMA = "core.material.f3.native_volume_mls.acceptance_reconciliation.v1"
UNKNOWN_LIMIT = 0.01
CDF_LIMIT = 0.02
NATIVE_INTERVAL_S = 0.002
CADENCE_TOLERANCE_S = 5.0e-5
FULL_WINDOW_S = 8.35

TRACE_TO_CHECKPOINT = {
    "core.material.f3.native_volume_mls.trace.v1":
    "core.material.f3.native_volume_mls.checkpoint.v1",
    "core.material.f3.native_volume_mls.trace.v2":
    "core.material.f3.native_volume_mls.checkpoint.v2",
    "core.material.f3.native_volume_mls.trace.temporal.v3":
    "core.material.f3.native_volume_mls.checkpoint.temporal.v3",
}

DEFAULT_OUTPUT_NAME = (
    "campaigns/core-v1/material/evidence/"
    "f3-native-mls-acceptance-bridge-v2/reconciliation-v1-20260922.json"
)
DEFAULT_REPORT_NAME = (
    "reports/F3-NATIVE-MLS-ACCEPTANCE-BRIDGE-V2-2026-09-22.zh-CN.md"
)

# These are deliberately all JSON/text inputs.  In particular, no HDF5 path
# is an input to this read-only collector.  HDF5 hashes are retained only as
# inherited values inside immutable upstream receipts.
INPUTS: dict[str, Path] = {
    "core_material": Path("scripts/core_material.py"),
    "core_material_acceptance": Path("scripts/core_material_acceptance.py"),
    "native_mls": Path("scripts/f3_native_volume_mls.py"),
    "native_mls_compare": Path("scripts/f3_native_volume_mls_compare.py"),
    "native_mls_temporal_v3": Path("scripts/f3_native_volume_mls_temporal_v3.py"),
    "gap_audit_v2": Path(
        "campaigns/core-v1/material/evidence/"
        "f3-t2-admission-acceptance-gap-audit-v2-20260922.json"
    ),
    "source_closure_audit_v1": Path(
        "campaigns/core-v1/material/evidence/f3-t2-source-closure-audit-v1-20260922.json"
    ),
    "prior_bridge_v2": Path(
        "campaigns/core-v1/material/evidence/f3-native-mls-acceptance-bridge-v2-20260922.json"
    ),
    "matrix_gap_audit": Path(
        "campaigns/core-v1/material/evidence/f3-native-mls-33-matrix-gap-audit-v1.json"
    ),
    "row24_negative_receipt": Path(
        "campaigns/core-v1/material/evidence/"
        "f3-row24-native002-vs-matched010-negative-acceptance-receipt-20260922.json"
    ),
    "row24_comparison": Path(
        "campaigns/core-v1/material/evidence/"
        "f3-row24-native002-vs-matched010-comparison-20260922.json"
    ),
    "row28_profile_receipt": Path(
        "campaigns/core-v1/material/evidence/"
        "f3-t2-seed-density-s4-row28-profile20-receipt-v1.json"
    ),
    "row28_source_preflight": Path(
        "campaigns/core-v1/material/derived/"
        "f3-t2-seed-density-s4-row28-profile20-v1/source-preflight.json"
    ),
    "row28_trace_summary": Path(
        "campaigns/core-v1/material/derived/"
        "f3-t2-seed-density-s4-row28-profile20-v1/trace.summary.json"
    ),
    "row28_checkpoint_manifest": Path(
        "campaigns/core-v1/material/derived/"
        "f3-t2-seed-density-s4-row28-profile20-v1/trace.h5.checkpoint.json"
    ),
    "dense_source_preflight": Path(
        "campaigns/core-v1/runtime/attempts/"
        "ada-f3-native-mls-dense-native002-production-s4-full835-v2/"
        "20260920T000456-ba294af97b9d/source-preflight.json"
    ),
    "bridge_implementation": Path(__file__),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve(lab_root: Path, value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    root = Path(lab_root).resolve()
    candidates = (root / path, root.parent / path)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _display(lab_root: Path, path: Path) -> str:
    path = Path(path).resolve()
    try:
        return str(path.relative_to(Path(lab_root).resolve()))
    except ValueError:
        return str(path)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _bind(lab_root: Path, value: str | Path, role: str) -> dict[str, Any]:
    path = _resolve(lab_root, value)
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": _display(lab_root, path),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "role": role,
        "read_only_input": True,
    }


def _input_bindings(lab_root: Path) -> dict[str, dict[str, Any]]:
    return {
        name: _bind(lab_root, path, "current source or immutable upstream receipt")
        for name, path in INPUTS.items()
    }


def _matrix_rows(matrix: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source in matrix.get("rows", []):
        row = int(source["matrix_index"])
        job = source.get("observed_job") or {}
        if row == 24:
            reconciliation_status = "terminal_negative_receipt_zero_credit"
        elif row == 28:
            reconciliation_status = "profile_source_audit_only_zero_credit"
        elif row == 32:
            reconciliation_status = "source_available_but_no_source_audit"
        elif source.get("status") == "terminal_diagnostic_observed":
            reconciliation_status = "terminal_diagnostic_no_formal_acceptance"
        elif source.get("status") == "terminal_matched_decimation_diagnostic_only":
            reconciliation_status = "matched_decimation_diagnostic_no_native_acceptance"
        elif source.get("status") in {
            "blocked_missing_registered_source",
            "source_available_not_submitted",
            "native_dense_material_postprocess_running",
            "related_v3_s2_diagnostic_running_not_canonical_s4_row",
        }:
            reconciliation_status = "blocked_or_pending_exact_source"
        else:
            reconciliation_status = "unclassified_fail_closed"
        rows.append(
            {
                "row": row,
                "configuration_id": source.get("configuration_id"),
                "matrix_stage": source.get("matrix_stage"),
                "cadence": source.get("cadence"),
                "seeds": source.get("seeds"),
                "q": source.get("q"),
                "status_from_registered_matrix": source.get("status"),
                "source_asset_status_from_registered_audit": source.get(
                    "source_asset_status_from_registered_audit"
                ),
                "blocking_assets": list(source.get("blocking_assets") or []),
                "observed_job_id": job.get("job_id"),
                "observed_job_status": job.get("status"),
                "formal_row_complete": bool(source.get("formal_row_complete")),
                "formal_acceptance_receipt": False,
                "reconciliation_status": reconciliation_status,
                "qualification_claim": "none",
                "credit": 0,
            }
        )
    if [row["row"] for row in rows] != list(range(33)):
        raise ValueError("registered F3 matrix is not exactly rows 0..32")
    return rows


def _row28_reconciliation(profile: dict[str, Any], summary: dict[str, Any], preflight: dict[str, Any]) -> dict[str, Any]:
    window = summary.get("source_window") or {}
    binding = summary.get("binding") or {}
    checkpoint = binding.get("checkpoint") or {}
    actual_frames = window.get("frame_count_committed")
    actual_end = window.get("time_end_s")
    return {
        "row": 28,
        "case_id": (profile.get("scope") or {}).get("case_id"),
        "source_audit_present": True,
        "source_audit_kind": "short_profile_not_full_acceptance_source",
        "source_preflight_schema": preflight.get("schema"),
        "trace_schema": binding.get("schema"),
        "checkpoint_schema": checkpoint.get("schema"),
        "required_window_s": FULL_WINDOW_S,
        "required_native_interval_s": NATIVE_INTERVAL_S,
        "observed_committed_frames": actual_frames,
        "required_full_window_frames": 836,
        "observed_time_end_s": actual_end,
        "full_event_window": bool(actual_end is not None and actual_end >= FULL_WINDOW_S),
        "right_censored": True,
        "unknown_fraction_max": (profile.get("result") or {}).get("unknown_fraction_max"),
        "mass_closed": (profile.get("result") or {}).get("mass_closed"),
        "first_passage_cdf_receipt": False,
        "return_cdf_receipt": False,
        "residence_cdf_receipt": False,
        "formal_acceptance_receipt": False,
        "qualification_claim": "none",
        "credit": 0,
        "blocking_reasons": [
            "profile stops at approximately 0.2 s and is not the registered 8.35 s acceptance window",
            "profile receipt has no formal first-passage/return/residence CDF package",
            "diagnostic source completion cannot promote matrix row 28 to T2",
        ],
    }


def _row32_reconciliation(matrix_row: dict[str, Any]) -> dict[str, Any]:
    return {
        "row": 32,
        "case_id": "F3_REV075_R075-ENDPOINT-HIGH-0075",
        "source_audit_present": False,
        "source_audit_kind": "none_found_in_current_evidence_namespace",
        "source_asset_status_from_registered_matrix": matrix_row.get(
            "source_asset_status_from_registered_audit"
        ),
        "required_window_s": FULL_WINDOW_S,
        "required_native_interval_s": NATIVE_INTERVAL_S,
        "full_event_window": False,
        "right_censored": True,
        "per_source_unknown_receipt": False,
        "first_passage_cdf_receipt": False,
        "return_cdf_receipt": False,
        "residence_cdf_receipt": False,
        "formal_acceptance_receipt": False,
        "qualification_claim": "none",
        "credit": 0,
        "blocking_reasons": [
            "no exact row-32 native source audit or terminal source-consumer receipt",
            "source-available matrix status is not a source output and cannot substitute for one",
        ],
    }


def _dense_cadence_failure(preflight: dict[str, Any]) -> dict[str, Any]:
    source = preflight.get("source") or {}
    frame = preflight.get("frame_selection") or {}
    declared = source.get("native_output_interval_nominal_s")
    observed = frame.get("selected_interval_median_s")
    return {
        "required_native_interval_s": NATIVE_INTERVAL_S,
        "tolerance_s": CADENCE_TOLERANCE_S,
        "declared_nominal_interval_s": declared,
        "observed_median_interval_s": observed,
        "observed_interval_error_s": (
            abs(float(observed) - NATIVE_INTERVAL_S) if observed is not None else None
        ),
        "source_frames": frame.get("source_frame_count"),
        "time_end_s": frame.get("selected_time_end_s"),
        "interpolation": frame.get("interpolation"),
        "cadence_gate_pass": False,
        "failure_class": "dense_source_preflight_nominal_interval_mismatch",
        "reason": (
            "the dense source is observed near .002 s, but its retained source-preflight "
            "declares native_output_interval_nominal_s=.01; provenance is not accepted "
            "until the declaration and frame map agree"
        ),
    }


def build_reconciliation(lab_root: Path) -> dict[str, Any]:
    lab_root = Path(lab_root).resolve()
    gap = _load(_resolve(lab_root, INPUTS["gap_audit_v2"]))
    closure = _load(_resolve(lab_root, INPUTS["source_closure_audit_v1"]))
    prior = _load(_resolve(lab_root, INPUTS["prior_bridge_v2"]))
    matrix = _load(_resolve(lab_root, INPUTS["matrix_gap_audit"]))
    row24 = _load(_resolve(lab_root, INPUTS["row24_negative_receipt"]))
    row24_comparison = _load(_resolve(lab_root, INPUTS["row24_comparison"]))
    row28 = _load(_resolve(lab_root, INPUTS["row28_profile_receipt"]))
    row28_preflight = _load(_resolve(lab_root, INPUTS["row28_source_preflight"]))
    row28_summary = _load(_resolve(lab_root, INPUTS["row28_trace_summary"]))
    dense_preflight = _load(_resolve(lab_root, INPUTS["dense_source_preflight"]))

    rows = _matrix_rows(matrix)
    row28_view = _row28_reconciliation(row28, row28_summary, row28_preflight)
    row32_view = _row32_reconciliation(next(item for item in rows if item["row"] == 32))
    row24_observed = row24.get("observed") or {}
    row24_gates = row24.get("gate_results") or {}
    row24_cdf = row24_observed.get("by_source") or {}

    retained_unknown = prior.get("per_source_unknown") or {}
    retained_cdf = prior.get("cdf_bounds") or {}
    source_window = prior.get("source_window_provenance") or {}
    prior_cadence = prior.get("cadence_provenance") or {}
    canary = prior_cadence.get("bounded_canary") or {}
    gap_comparison = gap.get("observed_gate_comparison") or {}
    gap_source = gap_comparison.get("source_window") or {}

    binding = _input_bindings(lab_root)
    blocking = [
        f"retained per-source unknown maximum {retained_unknown.get('maximum_observed')} exceeds {UNKNOWN_LIMIT}",
        f"retained first-passage/return/residence CDF maximum {retained_cdf.get('maximum_observed')} exceeds {CDF_LIMIT}",
        "row 24 is a negative scientific receipt: first-passage and return CDF gates fail despite complete window",
        "dense source cadence provenance fails closed because retained nominal interval .01 disagrees with required .002",
        "row 28 has only a short profile source audit; row 32 has no exact source audit",
        "rows 16-23, 26-27, 29 and 31 remain missing exact root-owned CFD sources",
        "all 33 matrix rows lack an independent formal acceptance receipt",
    ]

    value: dict[str, Any] = {
        "schema": SCHEMA,
        "versioned_namespace": "f3-native-mls-acceptance-bridge-v2/reconciliation-v1",
        "created_at_utc": utc_now(),
        "review_model": "gpt-5.6-terra",
        "status": "blocked_for_acceptance_zero_credit",
        "decision": "read_only_reconciliation_complete_no_qualification",
        "candidate": {
            "id": "f3-native-mls-acceptance-reconciliation-v2",
            "qualification_claim": "none",
            "credit": 0,
            "T2_macro": False,
            "T2_path": False,
        },
        "qualification_claim": "none",
        "credit": 0,
        "qualification_credit": 0,
        "T2_macro": False,
        "T2_path": False,
        "fixed_gates": {
            "unknown_fraction_per_source_max": UNKNOWN_LIMIT,
            "cdf_sup_abs_difference_max": CDF_LIMIT,
            "native_source_interval_s": NATIVE_INTERVAL_S,
            "native_cadence_tolerance_s": CADENCE_TOLERANCE_S,
            "full_source_window_s": FULL_WINDOW_S,
            "right_censored_is_not_acceptance": True,
            "no_partial_credit": True,
        },
        "trace_and_checkpoint_schema": {
            "accepted_pairs": dict(TRACE_TO_CHECKPOINT),
            "observed_row24": {
                "trace_schema": row24_comparison.get("left", {}).get("schema"),
                "checkpoint_schema": TRACE_TO_CHECKPOINT.get(
                    row24_comparison.get("left", {}).get("schema")
                ),
                "schema_binding_inherited": True,
            },
            "observed_row28": {
                "trace_schema": (row28_summary.get("binding") or {}).get("schema"),
                "checkpoint_schema": ((row28_summary.get("binding") or {}).get("checkpoint") or {}).get("schema"),
                "schema_binding_inherited": True,
            },
            "schema_gate_pass": True,
            "interpretation": "schema binding is necessary provenance, not material acceptance",
        },
        "source_cadence_and_window": {
            "required_full_window_s": FULL_WINDOW_S,
            "required_native_interval_s": NATIVE_INTERVAL_S,
            "retained_full_window_audit": {
                "path": source_window.get("audit_binding", {}).get("path"),
                "rows": source_window.get("rows", []),
                "source_window_gate": bool(gap_source.get("source_window_integrity_pass")),
            },
            "row24": {
                "full_window": bool(row24_observed.get("source_window_complete")),
                "right_censored": False,
                "cadence_gate": bool(row24_gates.get("source_window_complete")),
                "credit": 0,
            },
            "bounded_canary": {
                "full_window": bool(canary.get("full_event_window")),
                "right_censored": bool(canary.get("right_censored")),
                "time_end_s": canary.get("time_end_s"),
                "credit": 0,
            },
            "dense_cadence_failure": _dense_cadence_failure(dense_preflight),
            "row28": {
                "full_window": row28_view["full_event_window"],
                "observed_time_end_s": row28_view["observed_time_end_s"],
                "credit": 0,
            },
            "row32": {"full_window": False, "source_audit_present": False, "credit": 0},
        },
        "per_source_unknown": {
            "limit": UNKNOWN_LIMIT,
            "retained_full_window": retained_unknown,
            "row24": {
                "source_values": {
                    str(source): {
                        "unknown_fraction_left": values.get("unknown_fraction_left"),
                        "unknown_fraction_right": values.get("unknown_fraction_right"),
                        "gate_pass": max(
                            values.get("unknown_fraction_left", 1.0),
                            values.get("unknown_fraction_right", 1.0),
                        ) <= UNKNOWN_LIMIT,
                    }
                    for source, values in row24_cdf.items()
                },
                "gate_pass": bool(row24_gates.get("unknown_gate_pass")),
            },
            "row28": {"maximum_observed": row28_view["unknown_fraction_max"], "gate_pass": True},
            "row32": {"maximum_observed": None, "gate_pass": False, "receipt_present": False},
            "all_required_sources_have_receipts": False,
            "all_rows_pass": False,
        },
        "cdf_metrics": {
            "events": ["first_passage", "return", "residence"],
            "limit": CDF_LIMIT,
            "retained_full_window": retained_cdf,
            "row24": {
                "by_source": row24_cdf,
                "first_passage_receipt": True,
                "return_receipt": True,
                "residence_receipt": True,
                "gate_results": row24_gates,
                "scientific_acceptance": False,
                "credit": 0,
            },
            "row28": {
                "first_passage_receipt": False,
                "return_receipt": False,
                "residence_receipt": False,
                "scientific_acceptance": False,
                "credit": 0,
            },
            "row32": {
                "first_passage_receipt": False,
                "return_receipt": False,
                "residence_receipt": False,
                "scientific_acceptance": False,
                "credit": 0,
            },
            "all_required_sources_have_receipts": False,
            "all_rows_pass": False,
        },
        "right_censoring": {
            "policy": "unknown and right-censored paths remain in the full source denominator",
            "right_censored_is_not_acceptance": True,
            "bounded_canary_is_right_censored": bool(canary.get("right_censored")),
            "row28_is_right_censored": True,
            "row32_is_right_censored": True,
            "partial_credit": False,
        },
        "source_closure_reconciliation": {
            "historical_closure_receipt_preserved": True,
            "historical_gap_receipt_preserved": True,
            "rows_28_32": {
                "inherited_source_closure_view": closure.get("rows_28_32"),
                "reconciled_row28": row28_view,
                "reconciled_row32": row32_view,
            },
            "row24_negative_receipt": {
                "status": row24.get("status"),
                "qualification_claim": row24.get("qualification_claim"),
                "credit": row24.get("qualification_credit"),
                "gate_results": row24_gates,
                "blocking_reasons": row24.get("blocking_reasons", []),
            },
            "dense_cadence_failure": _dense_cadence_failure(dense_preflight),
            "missing_exact_sources": gap.get("matrix", {}).get("gap_groups", []),
        },
        "matrix": {
            "registered_row_count": len(rows),
            "registered_row_order": "0-23 resolution_substep; 24-27 cadence; 28-32 seed_density",
            "rows": rows,
            "formal_acceptance_receipt_count": 0,
            "material_matrix_ready": False,
            "diagnostic_rows_do_not_upgrade_t2": True,
        },
        "acceptance_gates": {
            "trace_schema_binding": True,
            "checkpoint_schema_binding": True,
            "source_cadence_provenance": False,
            "source_window_integrity": bool(gap_source.get("source_window_integrity_pass")),
            "per_source_unknown_fraction": False,
            "first_passage_return_residence_cdf": False,
            "right_censored_event": False,
            "full_event_window": False,
            "per_matrix_formal_acceptance_receipts": False,
        },
        "formal_acceptance_receipt": {
            "schema": RECEIPT_SCHEMA,
            "status": "blocked",
            "decision": "not_accepted",
            "qualification_claim": "none",
            "credit": 0,
            "T2_macro": False,
            "T2_path": False,
        },
        "blocking_reasons": blocking,
        "execution_constraints": {
            "read_only": True,
            "json_and_source_only": True,
            "hdf5_opened": False,
            "source_h5_opened": False,
            "terminal_h5_opened": False,
            "solver_started": False,
            "gpu_started": False,
            "queue_started": False,
            "new_cfd_generated": False,
            "new_job_submitted": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "central_ledger_mutation": 0,
            "matrix_mutation": 0,
            "T1_denominator_changed": False,
            "T2_denominator_changed": False,
            "scientific_denominator_changed": False,
            "thresholds_changed": False,
            "historical_receipts_overwritten": False,
        },
        "input_bindings": binding,
        "interpretation_boundary": (
            "This versioned artifact reconciles existing evidence and repairs the "
            "current core_material.py hash closure by binding the current file. "
            "It does not rewrite historical receipts, reopen HDF5, generate CFD, "
            "or grant any qualification credit."
        ),
    }
    return value


def render_report(value: dict[str, Any], evidence_path: Path) -> str:
    gates = value["acceptance_gates"]
    dense = value["source_cadence_and_window"]["dense_cadence_failure"]
    row28 = value["source_closure_reconciliation"]["rows_28_32"]["reconciled_row28"]
    row32 = value["source_closure_reconciliation"]["rows_28_32"]["reconciled_row32"]
    lines = [
        "# F3 native-MLS acceptance bridge v2/source-closure reconciliation（2026-09-22）",
        "",
        "结论：本 artifact 是只读、fail-closed 的 source-closure reconciliation；不授予 T2，`qualification_claim=none`，`credit=0`，`T2_macro=false`，`T2_path=false`。",
        "",
        "本次只读取 JSON receipt 和源码文本/哈希；没有打开 HDF5，没有启动 solver、GPU、queue，没有生成 CFD，没有修改 registry、ledger、matrix 或 denominator，也没有覆盖历史 receipt。",
        "",
        f"artifact：`{evidence_path}`；namespace：`{value['versioned_namespace']}`。",
        "",
        "## 统一结果",
        "",
        f"- trace/checkpoint schema binding：`{gates['trace_schema_binding']}` / `{gates['checkpoint_schema_binding']}`；只表示 provenance，不表示 acceptance。",
        f"- per-source unknown：`{gates['per_source_unknown_fraction']}`，保留全分母和 right-censor，固定上限 `{UNKNOWN_LIMIT}`。",
        f"- first-passage/return/residence CDF：`{gates['first_passage_return_residence_cdf']}`，固定 sup 上限 `{CDF_LIMIT}`。",
        f"- dense cadence：`{gates['source_cadence_provenance']}`；声明 interval `{dense['declared_nominal_interval_s']}` s，而要求 `{NATIVE_INTERVAL_S}` s。",
        f"- full event window/right-censor：`{gates['full_event_window']}` / `{gates['right_censored_event']}`。",
        f"- 33-row formal receipts：`{value['matrix']['formal_acceptance_receipt_count']}`；matrix ready=`{value['matrix']['material_matrix_ready']}`。",
        "",
        "## rows 28/32、row 24 和缺失 source",
        "",
        f"- row 28：现有 profile source audit 存在，但仅提交 `{row28['observed_committed_frames']}` 帧、结束于 `{row28['observed_time_end_s']}` s；不是 8.35 s formal source，CDF/residence receipt 缺失，credit=0。",
        f"- row 32：当前 evidence namespace 没有 exact source audit；source-available matrix status 不等于 source output，credit=0。",
        "- row 24：完整 dense source 的 negative acceptance receipt 保留；first-passage/return CDF 失败，不能因 window complete 而转为正验收。",
        "- dense cadence：保留 nominal `.01` 与要求 `.002` 的不一致，fail closed；不会用 observed median 取代错误的声明。",
        "- missing exact sources：rows 16–23、26–27、29、31 仍按 gap audit 保持缺失，不以模板或其他 amplitude 替代。",
        "",
        "## 当前 core_material.py hash closure",
        "",
        "新 artifact 绑定当前 `scripts/core_material.py`；历史 gap audit 的旧 hash 仍只作为历史证据存在，没有篡改。后续任何正式 collector 必须重新验证本 artifact 的 input bindings。",
        "",
        "## blocking reasons",
        "",
    ]
    lines.extend(f"{i}. {reason}" for i, reason in enumerate(value["blocking_reasons"], 1))
    lines.extend(["", "## input hashes", ""])
    for name, binding in value["input_bindings"].items():
        lines.append(f"- `{name}`：`{binding['path']}` — `{binding['sha256']}`")
    return "\n".join(lines) + "\n"


def write_artifacts(value: dict[str, Any], output: Path, report: Path) -> None:
    output = Path(output).resolve()
    report = Path(report).resolve()
    if output.exists() or report.exists():
        raise FileExistsError("refusing to overwrite versioned reconciliation artifacts")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(value, output), encoding="utf-8")


def verify_receipt(path: Path, lab_root: Path) -> dict[str, Any]:
    value = _load(Path(path))
    if value.get("schema") != SCHEMA:
        raise ValueError("reconciliation schema mismatch")
    if value.get("qualification_claim") != "none" or value.get("credit") != 0:
        raise ValueError("reconciliation is not zero-credit")
    if value.get("T2_macro") is not False or value.get("T2_path") is not False:
        raise ValueError("reconciliation changed T2 state")
    if value.get("execution_constraints", {}).get("historical_receipts_overwritten") is not False:
        raise ValueError("historical receipt overwrite is not allowed")
    for name, binding in value.get("input_bindings", {}).items():
        bound = _resolve(Path(lab_root), binding["path"])
        if not bound.is_file():
            raise FileNotFoundError(bound)
        if bound.stat().st_size != binding["bytes"]:
            raise ValueError(f"input size changed: {name}")
        if sha256_file(bound) != binding["sha256"]:
            raise ValueError(f"input hash changed: {name}")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    lab_root = Path(__file__).resolve().parents[1]
    parser.add_argument("--lab-root", type=Path, default=lab_root)
    parser.add_argument("--output", type=Path, default=lab_root / DEFAULT_OUTPUT_NAME)
    parser.add_argument("--report", type=Path, default=lab_root / DEFAULT_REPORT_NAME)
    args = parser.parse_args(argv)
    value = build_reconciliation(args.lab_root.resolve())
    write_artifacts(value, args.output, args.report)
    print(json.dumps({"schema": value["schema"], "status": value["status"], "credit": value["credit"], "output": str(Path(args.output).resolve())}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
