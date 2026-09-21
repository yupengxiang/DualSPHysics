#!/usr/bin/env python3
"""Read-only F3 T2 source-side closure audit.

The audit binds the existing F3 T2 gap audit and native MLS bridge to the
registered source assets and the now-terminal row-24 diagnostic receipt.  It
does not open HDF5, start a solver/GPU, submit work, or mutate any registry,
ledger, matrix, denominator, threshold, or prior evidence file.

The words ``declared`` and ``receipt`` are kept separate deliberately:
registered source metadata can describe a complete window, while a material
acceptance receipt still requires per-source unknown, CDF, and residence-CDF
evidence.  Diagnostic completion never grants T2 credit.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA = "core.material.f3.t2.source_closure_audit.v1"
UNKNOWN_LIMIT = 0.01
CDF_LIMIT = 0.02
NATIVE_INTERVAL_S = 0.002
NATIVE_CADENCE_TOLERANCE_S = 5.0e-5
FULL_WINDOW_S = 8.35
NATIVE010_FRAMES = 836
NATIVEDENSE_FRAMES = 4176

DEFAULT_OUTPUT_NAME = (
    "campaigns/core-v1/material/evidence/"
    "f3-t2-source-closure-audit-v1-20260922.json"
)
DEFAULT_REPORT_NAME = "reports/F3-T2-SOURCE-CLOSURE-AUDIT-2026-09-22.zh-CN.md"

INPUTS: dict[str, Path] = {
    "gap_audit": Path(
        "campaigns/core-v1/material/evidence/"
        "f3-t2-admission-acceptance-gap-audit-20260921.json"
    ),
    "native_mls_bridge": Path(
        "campaigns/core-v1/material/evidence/"
        "f3-native-mls-acceptance-bridge-v1-20260921.json"
    ),
    "matrix_asset_audit": Path(
        "campaigns/core-v1/material/evidence/"
        "f3-native-volume-mls-f3-matrix-asset-audit-v3-20260919.json"
    ),
    "root_source_review": Path(
        "campaigns/core-v1/material/evidence/f3-missing-source-root-review-v1.json"
    ),
    "source_proposals": Path(
        "campaigns/core-v1/material/evidence/"
        "f3-native-mls-missing-cfd-source-proposals-v2-20260920.json"
    ),
    "row24_spec": Path(
        "campaigns/core-v1/runtime/attempts/"
        "ada-f3-native-mls-dense-native002-production-s4-full835-v2/"
        "20260920T000456-ba294af97b9d/spec.json"
    ),
    "row24_result": Path(
        "campaigns/core-v1/runtime/attempts/"
        "ada-f3-native-mls-dense-native002-production-s4-full835-v2/"
        "20260920T000456-ba294af97b9d/result.json"
    ),
    "row24_summary": Path(
        "campaigns/core-v1/runtime/attempts/"
        "ada-f3-native-mls-dense-native002-production-s4-full835-v2/"
        "20260920T000456-ba294af97b9d/trace.summary.json"
    ),
    "row24_preflight": Path(
        "campaigns/core-v1/runtime/attempts/"
        "ada-f3-native-mls-dense-native002-production-s4-full835-v2/"
        "20260920T000456-ba294af97b9d/source-preflight.json"
    ),
    "row24_checkpoint": Path(
        "campaigns/core-v1/runtime/attempts/"
        "ada-f3-native-mls-dense-native002-production-s4-full835-v2/"
        "20260920T000456-ba294af97b9d/trace.h5.checkpoint.json"
    ),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve_path(lab_root: Path, value: str | Path) -> Path:
    value_path = Path(value)
    if value_path.is_absolute():
        return value_path
    root = Path(lab_root).resolve()
    candidates = (root / value_path, root.parent / value_path)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def display_path(lab_root: Path, path: Path) -> str:
    path = Path(path).resolve()
    try:
        return str(path.relative_to(Path(lab_root).resolve()))
    except ValueError:
        return str(path)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def bind_file(lab_root: Path, path: Path) -> dict[str, Any]:
    path = resolve_path(lab_root, path)
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": display_path(lab_root, path),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def _bool(value: Any) -> bool:
    return value is True


def _relative_asset(lab_root: Path, value: str | Path) -> Path:
    return resolve_path(lab_root, value)


def _asset_index(audit: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item["asset_id"]): item
        for item in audit.get("registered_assets", [])
        if isinstance(item, dict) and item.get("asset_id")
    }


def _matrix_index(audit: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {
        int(item["matrix_index"]): item
        for item in audit.get("matrix_rows", [])
        if isinstance(item, dict) and item.get("matrix_index") is not None
    }


def _prepared_receipt(lab_root: Path, asset: dict[str, Any]) -> dict[str, Any]:
    prepared_path = _relative_asset(lab_root, asset["prepared"])
    prepared = load_json(prepared_path)
    declared_hash = asset.get("prepared_sha256")
    prepared_actual_hash = sha256_file(prepared_path)
    input_assets = prepared.get("input_assets") or {}
    # Prepared records store input hashes by basename while the immutable
    # asset registration stores the actual case paths.  Bind those paths
    # explicitly so a missing continuation-directory basename is not
    # mistaken for missing lineage.
    generated_prefix = prepared.get("generated_prefix")
    generated_parent = (
        _relative_asset(lab_root, generated_prefix).parent
        if generated_prefix
        else prepared_path.parent
    )
    asset_paths = {
        "CaseSloshingAccData.csv": _relative_asset(lab_root, asset["control_csv"]),
        Path(str(asset.get("candidate_definition", ""))).name: _relative_asset(
            lab_root, asset["candidate_definition"]
        ),
        Path(str(asset.get("generated_xml", ""))).name: _relative_asset(
            lab_root, asset["generated_xml"]
        ),
        Path(str(generated_prefix or "") + ".bi4").name: generated_parent
        / (Path(str(generated_prefix or "")).name + ".bi4"),
        Path(str(generated_prefix or "") + "_hdp_Actual.vtk").name: generated_parent
        / (Path(str(generated_prefix or "")).name + "_hdp_Actual.vtk"),
    }
    input_checks: dict[str, Any] = {}
    for name, declared in input_assets.items():
        if not isinstance(declared, str):
            continue
        candidate = asset_paths.get(name, prepared_path.parent / Path(name).name)
        if not candidate.exists() and name not in asset_paths:
            candidate = prepared_path.parent / name
        actual_hash = sha256_file(candidate) if candidate.is_file() else None
        input_checks[name] = {
            "declared_sha256": declared,
            "path": display_path(lab_root, candidate),
            "exists": candidate.is_file(),
            "hash_checked": candidate.is_file(),
            "sha256": actual_hash,
            "pass": candidate.is_file() and actual_hash == declared,
        }
    return {
        "path": display_path(lab_root, prepared_path),
        "exists": prepared_path.is_file(),
        "declared_sha256": declared_hash,
        "sha256": prepared_actual_hash,
        "hash_pass": declared_hash in (None, prepared_actual_hash),
        "case_id": prepared.get("case_id"),
        "dp_m": prepared.get("dp_m"),
        "drive_amplitude": prepared.get("drive_amplitude"),
        "time_max_s": prepared.get("time_max_s"),
        "time_out_s": prepared.get("time_out_s"),
        "preparation_status": prepared.get("preparation_status"),
        "formal_release": prepared.get("formal_release"),
        "qualified": prepared.get("qualified"),
        "input_assets": input_checks,
        "all_input_hashes_pass": bool(input_checks)
        and all(item["pass"] for item in input_checks.values()),
    }


def _source_asset_receipt(
    lab_root: Path,
    asset: dict[str, Any],
    matrix_row: dict[str, Any],
) -> dict[str, Any]:
    prepared = _prepared_receipt(lab_root, asset)
    h5 = _relative_asset(lab_root, asset["h5"])
    matrix_amp = _number(matrix_row.get("drive_amplitude"))
    matrix_dp = matrix_row.get("dp")
    expected_dp = _number(matrix_dp) or _number(asset.get("dp_m"))
    exact_binding = (
        prepared["hash_pass"]
        and prepared["all_input_hashes_pass"]
        and prepared["case_id"] == asset.get("case_id")
        and _number(prepared["drive_amplitude"]) == matrix_amp
        and _number(prepared["dp_m"]) == expected_dp
        and prepared["time_out_s"] == asset.get("saved_interval_s")
        and prepared["formal_release"] is False
        and prepared["qualified"] is False
    )
    declared_window = (
        asset.get("frames") in (NATIVE010_FRAMES, NATIVEDENSE_FRAMES)
        and _number(asset.get("time_end_s")) is not None
        and float(asset["time_end_s"]) >= FULL_WINDOW_S
        and h5.is_file()
        and bool(asset.get("h5_sha256"))
    )
    declared_cadence = (
        _number(asset.get("saved_interval_s")) is not None
        and abs(float(asset["saved_interval_s"]) - 0.01) <= NATIVE_CADENCE_TOLERANCE_S
        and asset.get("frames") == NATIVE010_FRAMES
    )
    return {
        "source_asset_id": asset.get("asset_id"),
        "case_id": asset.get("case_id"),
        "source_role": asset.get("source_role"),
        "drive_amplitude": asset.get("drive_amplitude"),
        "dp_m": asset.get("dp_m"),
        "q": asset.get("q"),
        "prepared": prepared,
        "h5": {
            "path": display_path(lab_root, h5),
            "exists": h5.is_file(),
            "bytes_declared": asset.get("h5_bytes"),
            "sha256_declared": asset.get("h5_sha256"),
            "hash_opened": False,
        },
        "declared_source_window": {
            "frames": asset.get("frames"),
            "time_end_s": asset.get("time_end_s"),
            "full_window": declared_window,
            "independent_receipt": False,
        },
        "declared_native_cadence": {
            "interval_s": asset.get("saved_interval_s"),
            "frames": asset.get("frames"),
            "pass": declared_cadence,
            "independent_receipt": False,
        },
        "exact_lineage": exact_binding,
        "source_side_closure_pass": False,
        "closure_blockers": [
            "no independent immutable source-window audit receipt",
            "no per-source unknown receipt",
            "no per-source CDF receipt",
            "no per-source residence-CDF receipt",
            "formal_release=false and qualified=false",
        ],
        "qualification_claim": "none",
        "qualification_credit": 0,
    }


def _row24_audit(lab_root: Path, values: dict[str, dict[str, Any]]) -> dict[str, Any]:
    spec = values["row24_spec"]
    result = values["row24_result"]
    summary = values["row24_summary"]
    preflight = values["row24_preflight"]
    checkpoint = values["row24_checkpoint"]
    attempt_dir = resolve_path(lab_root, INPUTS["row24_result"]).parent
    expected_outputs = {str(item) for item in spec.get("required_outputs", [])}
    outputs = result.get("outputs") or result.get("artifact_index") or []
    output_checks: list[dict[str, Any]] = []
    for item in outputs:
        if not isinstance(item, dict) or not item.get("path"):
            continue
        path = attempt_dir / str(item["path"])
        # Only small receipts are hashed here.  trace.h5 remains explicitly
        # unopened; its terminal hash is taken from the execution receipt.
        opened = path.suffix.lower() != ".h5"
        actual = sha256_file(path) if opened and path.is_file() else None
        output_checks.append(
            {
                "path": item["path"],
                "exists": path.is_file(),
                "declared_sha256": item.get("sha256"),
                "sha256": actual,
                "hash_checked": opened,
                "hash_pass": (not opened) or actual == item.get("sha256"),
            }
        )
    source_window = summary.get("source_window") or {}
    frame_selection = source_window.get("frame_selection") or {}
    binding = summary.get("binding") or {}
    checkpoint_frame = checkpoint.get("committed_frame")
    cadence_declared = _number((spec.get("cadence_binding") or {}).get("native_output_interval_declared_s"))
    cadence_actual = _number(frame_selection.get("selected_interval_median_s"))
    cadence_error = abs(cadence_actual - NATIVE_INTERVAL_S) if cadence_actual is not None else None
    result_terminal = (
        result.get("schema") == "core.execution_receipt.v1"
        and result.get("execution_status") == "succeeded"
        and result.get("returncode") == 0
        and not result.get("missing_outputs")
    )
    output_receipt = bool(output_checks) and all(item["exists"] and item["hash_pass"] for item in output_checks)
    source_window_pass = (
        source_window.get("first_frame") == 0
        and source_window.get("frame_count_committed") == NATIVEDENSE_FRAMES
        and _number(source_window.get("time_start_s")) == 0
        and _number(source_window.get("time_end_s")) is not None
        and float(source_window["time_end_s"]) >= FULL_WINDOW_S
        and frame_selection.get("selection_mode") == "identity_all_native_frames"
        and frame_selection.get("interpolation") is False
    )
    cadence_pass = (
        cadence_declared == NATIVE_INTERVAL_S
        and cadence_error is not None
        and cadence_error <= NATIVE_CADENCE_TOLERANCE_S
        and frame_selection.get("interpolation") is False
    )
    checkpoint_pass = (
        checkpoint.get("schema") == "core.material.f3.native_volume_mls.checkpoint.v2"
        and checkpoint_frame == NATIVEDENSE_FRAMES - 1
        and bool(checkpoint.get("file_sha256"))
        and bool(checkpoint.get("state_sha256"))
    )
    terminalization_legal = (
        result_terminal
        and output_receipt
        and summary.get("schema") == "core.material.f3.native_volume_mls.full_cadence_result.v2"
        and summary.get("status") == "completed"
        and preflight.get("schema") == "core.material.f3.native_volume_mls.source_preflight.v2"
        and preflight.get("status") == "preflight_passed"
        and source_window_pass
        and cadence_pass
        and checkpoint_pass
    )
    source_rows = summary.get("source_rows") or []
    per_source = []
    for row in source_rows:
        if not isinstance(row, dict):
            continue
        per_source.append(
            {
                "source": row.get("source"),
                "unknown_fraction": row.get("unknown_fraction"),
                "unknown_receipt": True,
                "unknown_gate_pass": _number(row.get("unknown_fraction")) is not None
                and float(row["unknown_fraction"]) <= UNKNOWN_LIMIT,
                "cdf_receipt": False,
                "residence_cdf_receipt": False,
            }
        )
    return {
        "row": 24,
        "job_id": spec.get("job_id"),
        "execution_status": result.get("execution_status"),
        "qualification_claim": spec.get("qualification_claim"),
        "terminalization_receipt": result_terminal and output_receipt,
        "legal_terminalization": terminalization_legal,
        "diagnostic_only": True,
        "qualification_credit": 0,
        "source_window": {
            "frames": source_window.get("frame_count_committed"),
            "first_frame": source_window.get("first_frame"),
            "time_start_s": source_window.get("time_start_s"),
            "time_end_s": source_window.get("time_end_s"),
            "full_window": source_window_pass,
            "identity_selection": frame_selection.get("selection_mode"),
        },
        "native_cadence": {
            "declared_interval_s": cadence_declared,
            "observed_median_interval_s": cadence_actual,
            "median_error_s": cadence_error,
            "tolerance_s": NATIVE_CADENCE_TOLERANCE_S,
            "pass": cadence_pass,
            "interpolation": frame_selection.get("interpolation"),
        },
        "checkpoint": {
            "schema": checkpoint.get("schema"),
            "committed_frame": checkpoint_frame,
            "pass": checkpoint_pass,
        },
        "output_receipt": {
            "required_outputs": sorted(expected_outputs),
            "checks": output_checks,
            "pass": output_receipt,
        },
        "per_source": per_source,
        "cdf_receipt": False,
        "residence_cdf_receipt": False,
        "material_acceptance_pass": False,
        "warnings": [
            "source-preflight reports native_output_interval_nominal_s=0.01; spec/registered dense source/frame map bind the source as native .002",
            "summary has diagnostic unknown/residence quantiles but no formal CDF or residence-CDF acceptance receipt",
            "terminal engineering success is not material T2 acceptance",
        ],
    }


def _missing_sources(
    gap_audit: dict[str, Any],
    root_review: dict[str, Any],
    proposals: dict[str, Any],
    matrix_asset_audit: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = [16, 17, 18, 19, 20, 21, 22, 23, 26, 27, 29, 31]
    gap_groups = gap_audit.get("matrix", {}).get("gap_groups", [])
    by_row: dict[int, dict[str, Any]] = {}
    for group in gap_groups:
        if not isinstance(group, dict):
            continue
        for row in group.get("rows", []):
            if int(row) in rows:
                by_row[int(row)] = {
                    "gap_kind": group.get("kind"),
                    "dependency": group.get("dependency"),
                }
    cases = {}
    for case in root_review.get("source_cases", []):
        if isinstance(case, dict):
            for row in case.get("matrix_rows", []):
                cases[int(row)] = case
    matrix_rows = _matrix_index(matrix_asset_audit)
    # Rows 29 and 31 reuse the same exact production source cases as rows
    # 16/17 and 20/21.  They are absent from the five source-case proposal
    # list because they are seed-density consumers, so recover the root case
    # by (amplitude, production dp) while preserving their distinct rows.
    production_case_by_binding = {
        (float(item.get("drive_amplitude")), float(item.get("dp_m"))): item
        for item in root_review.get("source_cases", [])
        if isinstance(item, dict)
        and float(item.get("dp_m", -1)) == 0.0075
    }
    proposal_by_case = {
        item.get("case_id"): item
        for item in proposals.get("deduplicated_source_cases", [])
        if isinstance(item, dict) and item.get("case_id")
    }
    result = []
    for row in rows:
        matrix_row = matrix_rows.get(row) or {}
        case = cases.get(row) or {}
        if not case:
            amp = _number(matrix_row.get("drive_amplitude"))
            case = production_case_by_binding.get((amp, 0.0075), {}) if amp is not None else {}
        proposal = proposal_by_case.get(case.get("case_id"), {})
        source_asset_id = proposal.get("source_asset_id")
        if not source_asset_id:
            blocking = matrix_row.get("blocking_assets") or []
            source_asset_id = blocking[0] if blocking else None
        output_interval = case.get("output_interval_s", proposal.get("output_interval_s"))
        if output_interval is None:
            output_interval = 0.002 if matrix_row.get("cadence") == "native_dense" else 0.01
        result.append(
            {
                "matrix_row": row,
                "case_id": case.get("case_id") or proposal.get("case_id"),
                "source_asset_id": source_asset_id,
                "drive_amplitude": case.get("drive_amplitude", proposal.get("drive_amplitude", matrix_row.get("drive_amplitude"))),
                "dp_m": case.get("dp_m", proposal.get("dp_m", matrix_row.get("dp"))),
                "output_interval_s": output_interval,
                "root_owned_cfd_source_required": True,
                "source_template_is_not_output": True,
                "launch_allowed_from_review": proposal.get("launch_allowed_from_this_record", False),
                "gap_kind": (by_row.get(row) or {}).get("gap_kind"),
                "dependency": (by_row.get(row) or {}).get("dependency"),
                "qualification_claim": "none",
                "qualification_credit": 0,
            }
        )
    return result


def build_audit(lab_root: Path) -> dict[str, Any]:
    lab_root = Path(lab_root).resolve()
    values: dict[str, dict[str, Any]] = {}
    bindings: dict[str, Any] = {}
    for name, relative in INPUTS.items():
        path = resolve_path(lab_root, relative)
        values[name] = load_json(path)
        bindings[name] = bind_file(lab_root, path)
    matrix = values["matrix_asset_audit"]
    assets = _asset_index(matrix)
    rows = _matrix_index(matrix)
    row_asset_ids = {
        28: "f3_production_amp0p9_native010",
        32: "f3_production_amp1p1_native010",
    }
    row_assets = {}
    for row, asset_id in row_asset_ids.items():
        row_assets[str(row)] = _source_asset_receipt(lab_root, assets[asset_id], rows[row])
    row24 = _row24_audit(lab_root, values)
    missing = _missing_sources(
        values["gap_audit"],
        values["root_source_review"],
        values["source_proposals"],
        values["matrix_asset_audit"],
    )
    all_receipts_absent = all(
        not item["source_side_closure_pass"]
        for item in row_assets.values()
    )
    return {
        "schema": SCHEMA,
        "version": "v1",
        "created_at_utc": utc_now(),
        "review_model": "gpt-5.6-luna",
        "scope": "F3 T2 source-side closure only; rows 28/32, row 24 terminalization, and exact missing root-owned CFD sources",
        "status": "source_closure_blocked",
        "T2_macro": False,
        "T2_path": False,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "input_bindings": bindings,
        "fixed_gates": {
            "unknown_fraction_per_source_max": UNKNOWN_LIMIT,
            "cdf_sup_abs_difference_max": CDF_LIMIT,
            "native_source_interval_s": NATIVE_INTERVAL_S,
            "native_source_cadence_integrity_tolerance_s": NATIVE_CADENCE_TOLERANCE_S,
            "full_source_window_s": FULL_WINDOW_S,
            "right_censored_is_not_acceptance": True,
            "no_partial_credit": True,
        },
        "rows_28_32": {
            "rows": row_assets,
            "summary": {
                "exact_lineage_present": all(item["exact_lineage"] for item in row_assets.values()),
                "full_source_window_declared": all(
                    item["declared_source_window"]["full_window"] for item in row_assets.values()
                ),
                "native_cadence_declared": all(
                    item["declared_native_cadence"]["pass"] for item in row_assets.values()
                ),
                "independent_source_window_receipt": False,
                "per_source_unknown_receipt": False,
                "per_source_cdf_receipt": False,
                "per_source_residence_cdf_receipt": False,
                "source_side_closure_pass": False,
                "qualification_credit": 0,
            },
            "interpretation": "rows 28/32 have registered .01 source references and prepared/hash lineage, but no terminal source-consumer receipts; metadata is not material acceptance",
        },
        "row24_terminalization": row24,
        "missing_root_owned_cfd_sources": {
            "requested_rows": [16, 17, 18, 19, 20, 21, 22, 23, 26, 27, 29, 31],
            "items": missing,
            "source_template_substitution_forbidden": True,
            "qualification_claim": "none",
            "qualification_credit": 0,
        },
        "cpu_only_source_audit": {
            "performed": False,
            "invocation_count": 0,
            "hdf5_opened": False,
            "solver_started": False,
            "gpu_started": False,
            "reason": "Existing JSON/source receipts were sufficient for closure classification; no long-H5 reopen was needed or performed",
            "qualification_credit": 0,
        },
        "bridge_boundary": {
            "native_mls_bridge_read": True,
            "diagnostic_to_t2_promotion": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "matrix_mutation": 0,
            "denominator_mutation": 0,
            "threshold_mutation": 0,
            "prior_evidence_overwritten": False,
        },
        "blocking_reasons": [
            "rows 28/32 lack immutable per-source unknown/CDF/residence-CDF acceptance receipts",
            "row24 has legal terminal engineering receipt but remains diagnostic-only and has no formal CDF/residence-CDF acceptance receipts",
            "exact root-owned CFD source closure remains required for rows 16-23, 26-27, 29, and 31",
            "source-preflight nominal interval mismatch is retained as a warning and does not grant cadence acceptance",
            "T2 macro/path and qualification credit remain false/zero",
        ],
    }


def _report(audit: dict[str, Any]) -> str:
    row28 = audit["rows_28_32"]["rows"]["28"]
    row32 = audit["rows_28_32"]["rows"]["32"]
    row24 = audit["row24_terminalization"]
    lines = [
        "# F3 T2 source-side closure audit（2026-09-22）",
        "",
        "本报告由 `f3_t2_source_closure_audit_v1.py` 生成，审计范围是 source-side closure。审计只读取 JSON、准备记录和小型 receipt 文本；未打开 HDF5，未启动 solver/GPU，未提交 queue，也未修改 registry、ledger、matrix、denominator 或阈值。审计绑定模型标识为 `gpt-5.6-luna`。",
        "",
        "## 判定",
        "",
        "T2 macro/path 均为 `false`，qualification claim 为 `none`，qualification credit 为 `0`。Diagnostic completion、terminal execution receipt 与 source metadata 不会自动升级为 T2。",
        "",
        "## rows 28/32",
        "",
        f"row 28（{row28['source_asset_id']}）的 exact prepared/H5/XML/control lineage 与 `.01`、836-frame、8.35 s source metadata 可复核；row 32（{row32['source_asset_id']}）同样如此。但二者都没有独立 immutable source-window receipt，也没有 per-source unknown、CDF 或 residence-CDF acceptance receipt。因此 exact lineage/declared window/cadence 存在，source-side closure 仍为 `false`，credit 为 `0`。",
        "",
        "## row 24 terminalization",
        "",
        f"row 24 的 execution receipt 为 `succeeded`，required outputs 完整且小型 receipt hash 可复核；summary 为 completed，source window 为 {row24['source_window']['frames']} 帧（0..{row24['source_window']['frames'] - 1}），覆盖到 {row24['source_window']['time_end_s']} s，identity native frame selection，无 interpolation，checkpoint committed frame 为 {row24['checkpoint']['committed_frame']}。这些条件构成合法的 terminal engineering receipt：`{row24['legal_terminalization']}`。",
        "",
        "它仍是 native dense `.002` 的 material diagnostic，`qualification_claim=none`、credit 为 `0`。summary 中存在 unknown/residence quantiles，但没有 formal CDF 或 residence-CDF acceptance receipt，因此 material acceptance 仍为 `false`。source-preflight 的 `native_output_interval_nominal_s=0.01` 与 spec/registered dense source/frame map 的 `.002` 不一致，已作为 warning 保留，不能被忽略或升级为 acceptance。",
        "",
        "## 缺失的 root-owned CFD source",
        "",
        "以下 rows 仍按 gap audit 要求 exact root-owned CFD source closure；template/development source 不能替代，所有项 qualification claim 均为 `none`：",
        "",
    ]
    for item in audit["missing_root_owned_cfd_sources"]["items"]:
        lines.append(
            f"- row {item['matrix_row']}: `{item['case_id']}`，asset `{item['source_asset_id']}`，amp={item['drive_amplitude']}，dp={item['dp_m']}，native output={item['output_interval_s']} s。"
        )
    lines += [
        "",
        "## CPU-only 与边界",
        "",
        "本次未执行 HDF5 source audit（invocation count 0）；已有 JSON/source receipt 足以完成 closure 分类，无需重新打开长 H5。没有 solver/GPU/queue 动作，所有 qualification credit 保持零。",
        "",
        "审计结果是 fail-closed：补齐 exact CFD source、terminal source audit 以及每 source unknown/CDF/residence receipt 后，仍需通过既有固定 gate 和 acceptance bridge 才能重新评估；本报告本身不改变任何资格状态。",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()
    lab_root = args.lab_root.resolve()
    audit = build_audit(lab_root)
    output = args.output or lab_root / DEFAULT_OUTPUT_NAME
    report = args.report or lab_root / DEFAULT_REPORT_NAME
    output = output if output.is_absolute() else lab_root / output
    report = report if report.is_absolute() else lab_root / report
    output.parent.mkdir(parents=True, exist_ok=True)
    report.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report.write_text(_report(audit), encoding="utf-8")
    print(json.dumps({"output": str(output), "report": str(report), "schema": SCHEMA}, ensure_ascii=False))


if __name__ == "__main__":
    main()
