#!/usr/bin/env python3
"""Build a read-only root-review boundary for the next F3/F4 T2 step.

The current F3/F4 records are both T1-qualified but remain T2-negative.  This
builder reads the existing JSON receipts and binds one smallest deferred
candidate: the F4 ``f4_ess32_v2`` full-source material sidecar contract.  It
does not open or rehash old HDF5, rerun CFD, start a solver/GPU/queue, write a
matrix, or mutate the ledger/registry.  The resulting contract is
proposal-only and grants zero T2 credit.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
OUTPUT = LAB / (
    "campaigns/core-v1/material/evidence/"
    "f3-f4-t2-admission-root-review-contract-20260921.json"
)
REPORT = LAB / "reports/F3-F4-T2-ADMISSION-CONTRACT-2026-09-21.zh-CN.md"

SOURCE_WINDOW_AUDIT = LAB / (
    "campaigns/core-v1/material/evidence/"
    "f3-f4-t2-cpu-source-window-audit-v1-20260920.json"
)
F4_SIDECAR_PREFLIGHT = LAB / (
    "campaigns/core-v1/material/evidence/"
    "f4-macro-t2-sidecar-preflight-20260920.json"
)
F4_FULL_SOURCE_CONTRACT = LAB / (
    "campaigns/core-v1/material/evidence/"
    "f4-tallwall120-native-cell14-f4-ess32-full-source-canary-contract-20260921.json"
)
F4_CANDIDATE_CONTRACT = LAB / (
    "campaigns/core-v1/material/evidence/"
    "f4-tallwall120-native-cell14-candidate-contract-20260921.json"
)
F4_ROOT_CAUSE_AUDIT = LAB / (
    "campaigns/core-v1/material/evidence/"
    "f4-tallwall120-native-cell14-root-cause-audit-20260921.json"
)
F4_MATERIAL_PREFLIGHT = LAB / (
    "campaigns/core-v1/material/evidence/"
    "f4-tallwall120-native-cell14-material-preflight-20260921.json"
)
F3_QUALIFICATION = LAB / "campaigns/core-v1/evidence/f3-inherited-qualification.json"
F4_QUALIFICATION = LAB / (
    "campaigns/core-v1/evidence/f4-tallwall120-formal-qualification-20260920.json"
)

SOURCE_SHA256 = "91846866c177e4c3036b7ef92c33a4e0bde7d9e8993efb01dde300811b7c096e"
SOURCE_PATH = (
    "campaigns/core-v1/cfd/f4-tallwall120-archives-v2/"
    "f4-tallwall120-qualification-cell-14/product/trajectory.h5"
)
SOURCE_BYTES = 10_326_356_548
SOURCE_FRAMES = 1086
SOURCE_PARTICLES = 217485
SOURCE_END_S = 4.340002980805959
UNKNOWN_LIMIT = 0.01
CDF_LIMIT = 0.02


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(LAB))


def bind(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": rel(path),
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "role": role,
    }


def _f3_summary(audit: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for row in audit["f3"]["rows"]:
        source_rows = row["trace_audit"]["source_rows"]
        rows.append(
            {
                "row": int(row["row"]),
                "case_id": row["case_id"],
                "source_window": {
                    "path": row["source_path"],
                    "sha256": row["source_audit"]["hash"]["sha256"],
                    "frames": row["source_audit"]["frames_scanned"],
                    "particles": row["source_audit"]["particle_count"],
                    "integrity_pass": row["source_audit"]["integrity_pass"],
                    "mass_closure_pass": row["source_audit"]["mass"]["mass_closure_pass"],
                },
                "material_trace": {
                    "path": row["trace_path"],
                    "sha256": row["trace_audit"]["hash"]["sha256"],
                    "frames": row["trace_audit"]["frames"],
                    "reader_reconstruction_pass": row["trace_audit"][
                        "reader_reconstruction_pass"
                    ],
                    "mass_closure_pass": row["trace_audit"]["seed_mass_closure"]["pass"],
                },
                "source_rows": [
                    {
                        "source_id": item["source_id"],
                        "seed_denominator": item["seed_denominator"],
                        "terminal_unknown_fraction": item["terminal_unknown_fraction"],
                        "unknown_gate_pass": item["unknown_gate_pass"],
                    }
                    for item in source_rows
                ],
                "cdf_maxima": {
                    source_id: value["maximum"]
                    for source_id, value in row["cdf_comparison"].items()
                },
                "qualification_credit": row["qualification_credit"],
            }
        )
    return rows


def _f4_summary(audit: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "canary_id": row["canary_id"],
            "case_id": row["case_id"],
            "seed_denominator": row["trace_audit"]["seed_count"],
            "unknown_fraction_max": row["unknown_fraction_max"],
            "unknown_gate_pass": row["trace_audit"]["unknown_gate"]["pass"],
            "mass_closed": row["mass_closed"],
            "event_window_complete": row["event_window_complete"],
            "event_window_status": row["trace_audit"]["event_window"]["status"],
            "qualification_credit": row["qualification_credit"],
        }
        for row in audit["f4"]["cases"]
    ]


def build_contract() -> dict[str, Any]:
    audit = load(SOURCE_WINDOW_AUDIT)
    sidecar = load(F4_SIDECAR_PREFLIGHT)
    full = load(F4_FULL_SOURCE_CONTRACT)
    candidate = load(F4_CANDIDATE_CONTRACT)
    root_cause = load(F4_ROOT_CAUSE_AUDIT)
    material_preflight = load(F4_MATERIAL_PREFLIGHT)
    f3_qualification = load(F3_QUALIFICATION)
    f4_qualification = load(F4_QUALIFICATION)

    assert audit["schema"] == "core.material.t2.cpu_source_window_audit.v1"
    assert audit["status"] == "completed_negative_cpu_audit"
    assert audit["gate_evaluation"] == {
        "T2_macro": False,
        "T2_path": False,
        "f3_cdf_pass": False,
        "f4_event_window_pass": False,
        "qualification_claim": "none",
        "qualification_credit": "none",
        "source_reader_reconstruction_integrity_pass": True,
        "unknown_mass_pass": False,
    }
    assert audit["execution_constraints"]["cpu_only"] is True
    assert audit["execution_constraints"]["solver_started_by_audit"] is False
    assert audit["execution_constraints"]["gpu_started_by_audit"] is False
    assert audit["execution_constraints"]["new_job_submitted"] is False

    assert sidecar["status"] == "blocked_for_qualification"
    assert sidecar["T2_macro"] is False
    assert sidecar["T2_path"] is False
    assert sidecar["gate_evaluation"]["unknown_mass_pass"] is False
    assert sidecar["gate_evaluation"]["event_window_pass"] is False
    assert sidecar["gate_evaluation"]["sidecar_provenance_pass"] is True
    assert sidecar["gate_evaluation"]["sidecar_independent_cfd_pass"] is False
    assert sidecar["gate_evaluation"]["static_cfd_matrix_complete"] is False
    assert sidecar["execution_constraints"]["new_job_submitted"] is False
    assert sidecar["execution_constraints"]["solver_started"] is False
    assert sidecar["execution_constraints"]["gpu_started"] is False

    assert f3_qualification["T1_numerical"] is True
    assert f3_qualification["T2_macro"] is False
    assert f3_qualification["T2_path"] is False
    assert f3_qualification["matrix_complete"] is True
    assert f4_qualification["T1_numerical"] is True
    assert f4_qualification["T2_macro"] is False
    assert f4_qualification["T2_path"] is False
    assert f4_qualification["matrix_complete"] is True

    assert full["status"] == "proposal_only_deferred_after_one_transition_failure"
    assert full["route_decision"]["automatic_execution"] is False
    assert full["route_decision"]["decision"] == "deferred"
    assert full["candidate"]["candidate_id"] == "f4_ess32_v2"
    assert full["candidate"]["qualification_credit"] == "none"
    assert full["candidate"]["qualification_status"] == "proposal_only"
    assert full["candidate"]["unknown_fraction_limit"] == UNKNOWN_LIMIT
    assert full["candidate"]["event_gate_changed"] is False
    assert full["candidate"]["cdf_changed"] is False
    assert full["candidate"]["one_transition_counterfactual"][
        "counterfactual_cohort_survivors"
    ] == 0
    assert full["source_window"]["frame_start"] == 0
    assert full["source_window"]["frame_end"] == SOURCE_FRAMES - 1
    assert full["source_window"]["frame_count"] == SOURCE_FRAMES
    assert full["source_window"]["particle_count"] == SOURCE_PARTICLES
    assert full["source_window"]["time_end_s"] == SOURCE_END_S
    assert full["source_window"]["native_rows_exact"] is True
    assert full["source_window"]["no_stride_or_synthetic_cadence"] is True
    assert full["execution"]["output_stem_is_new"] is True
    output_stem = Path(full["execution"]["output_stem"])
    assert not output_stem.exists()
    assert full["execution"]["existing_trace_reuse"]["binding_only"] is True
    assert full["execution"]["existing_trace_reuse"]["candidate_output_reuse"] is False
    assert full["execution_constraints"]["proposal_only"] is True
    assert full["execution_constraints"]["solver_started"] is False
    assert full["execution_constraints"]["gpu_started"] is False
    assert full["execution_constraints"]["queue_mutation"] == 0
    assert full["execution_constraints"]["registry_mutation"] == 0
    assert full["execution_constraints"]["central_ledger_mutation"] == 0

    assert candidate["schema"] == "core.material.f4.tallwall120.candidate_contract.v1"
    assert candidate["source_sha256"] == SOURCE_SHA256
    ess32 = candidate["contracts"]["f4_ess32_v2"]
    assert ess32["backend"] == "f4_ckdtree_visible_shepard_ess32_v2"
    assert ess32["neighbours"] == 32
    assert ess32["unknown_fraction_limit"] == UNKNOWN_LIMIT
    assert ess32["unknown_gate_changed"] is False
    assert ess32["cdf_changed"] is False
    assert ess32["event_gate_changed"] is False
    assert candidate["candidate_evaluation"]["f4_ess32_v2"][
        "counterfactual_cohort_survivors"
    ] == 0
    assert root_cause["qualification"]["T2_macro"] is False
    assert root_cause["qualification"]["T2_path"] is False
    assert root_cause["qualification"]["qualification_credit"] == "none"
    assert material_preflight["qualification"]["T2_macro"] is False
    assert material_preflight["qualification"]["T2_path"] is False
    assert material_preflight["gate_evaluation"]["unknown_fraction"] == 0.998046875
    assert material_preflight["gate_evaluation"]["event_window_complete"] is False
    assert material_preflight["execution_constraints"]["scientific_denominator_changed"] is False

    source_binding = full["source_window"]["source"]
    assert source_binding["sha256"] == SOURCE_SHA256
    assert source_binding["path"].endswith(SOURCE_PATH)
    source_path = Path(source_binding["path"])
    assert source_path.is_file()

    hash_bindings = {
        "f3_f4_cpu_source_window_audit": bind(
            SOURCE_WINDOW_AUDIT, "current negative F3/F4 source-window audit"
        ),
        "f4_macro_sidecar_preflight": bind(
            F4_SIDECAR_PREFLIGHT, "current negative F4 macro sidecar preflight"
        ),
        "f4_full_source_candidate_contract": bind(
            F4_FULL_SOURCE_CONTRACT, "deferred F4 ESS32 full-source contract"
        ),
        "f4_candidate_contract": bind(
            F4_CANDIDATE_CONTRACT, "F4 ESS32 one-transition candidate contract"
        ),
        "f4_root_cause_audit": bind(
            F4_ROOT_CAUSE_AUDIT, "F4 first-failure root-cause audit"
        ),
        "f4_material_preflight": bind(
            F4_MATERIAL_PREFLIGHT, "F4 bounded negative material preflight"
        ),
        "f3_t1_qualification": bind(F3_QUALIFICATION, "F3 T1 qualification receipt"),
        "f4_t1_qualification": bind(F4_QUALIFICATION, "F4 T1 qualification receipt"),
        "implementation": bind(Path(__file__), "T2 admission contract implementation"),
        "test": bind(
            LAB / "tests/test_f3_f4_t2_admission_contract_v1.py",
            "T2 admission contract regression test",
        ),
    }

    f3_rows = _f3_summary(audit)
    f4_rows = _f4_summary(audit)
    return {
        "schema": "core.material.t2.f3_f4.admission.root_review_only.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "proposal_only_root_review_required",
        "record_id": "f3-f4-t2-admission-root-review-contract-20260921",
        "qualification_claim": "none",
        "qualification_credit": "none",
        "T2_macro": False,
        "T2_path": False,
        "selected_route": {
            "family": "F4",
            "scope_id": "F4_resting_pool_laminar_tallwall120_x_v1",
            "candidate_id": "f4_ess32_v2",
            "decision": "select_smallest_deferred_full_source_material_candidate",
            "reason": [
                "F3 has complete source/window integrity but both retained rows fail the fixed unknown and CDF gates, with no equally bounded fresh candidate contract.",
                "F4 has a T1-qualified 1086-frame native source through 4.340002980805959 s and a hash-bound ESS32 candidate/full-source contract.",
                "The F4 ESS32 one-transition cohort has zero survivors, so this is a diagnostic proposal and cannot be treated as a likely qualification or T2 pass.",
            ],
            "candidate_status": "deferred_proposal_only",
            "existing_output_stem_is_unmaterialized": True,
        },
        "current_qualification_state": {
            "F3": {
                "T1_numerical": f3_qualification["T1_numerical"],
                "T2_macro": f3_qualification["T2_macro"],
                "T2_path": f3_qualification["T2_path"],
                "matrix_complete": f3_qualification["matrix_complete"],
            },
            "F4": {
                "T1_numerical": f4_qualification["T1_numerical"],
                "T2_macro": f4_qualification["T2_macro"],
                "T2_path": f4_qualification["T2_path"],
                "matrix_complete": f4_qualification["matrix_complete"],
            },
            "overall_T2_credit": 0,
            "core_gate_changed": False,
        },
        "historical_audit": {
            "f3": {
                "rows": f3_rows,
                "cdf_limit": CDF_LIMIT,
                "cdf_pass": False,
                "maximum_unknown_fraction": 0.015625,
                "unknown_limit": UNKNOWN_LIMIT,
                "integrity_and_mass_closure_pass": True,
            },
            "f4": {
                "cases": f4_rows,
                "unknown_limit": UNKNOWN_LIMIT,
                "all_event_windows_complete": False,
                "all_mass_closed": True,
                "sidecar_provenance_is_not_independent_cfd": True,
            },
            "qualification_claim": "none",
            "credit": 0,
        },
        "source_window_binding": {
            "path": SOURCE_PATH,
            "sha256": SOURCE_SHA256,
            "bytes": SOURCE_BYTES,
            "frames": SOURCE_FRAMES,
            "particles": SOURCE_PARTICLES,
            "time_start_s": 0.0,
            "time_end_s": SOURCE_END_S,
            "native_rows_exact": True,
            "no_stride_or_synthetic_cadence": True,
            "hash_source": "existing F4 preflight/full-source receipts; admission contract does not reopen or rehash HDF5",
        },
        "candidate_contract": {
            "candidate_id": "f4_ess32_v2",
            "backend": ess32["backend"],
            "neighbours": ess32["neighbours"],
            "regularization_m": ess32["regularization_m"],
            "maximum_support_distance_m": ess32["maximum_support_distance_m"],
            "fixed_reconstruction_gate": ess32["fixed_gate"],
            "unknown_fraction_limit": UNKNOWN_LIMIT,
            "event_gate_changed": False,
            "cdf_changed": False,
            "denominator_policy": "all 512 geometric seeds; unknown/right-censor retained",
            "one_transition_counterfactual_survivors": 0,
            "qualification_credit": "none",
        },
        "sole_future_authorization_boundary": {
            "status": "root_review_only_no_current_authorization",
            "authorized_now": False,
            "if_explicitly_authorized": {
                "action": "run exactly one CPU-only F4 ESS32 full-source material sidecar on the bound existing T1 source",
                "candidate_id": "f4_ess32_v2",
                "output_stem": full["execution"]["output_stem"],
                "scope": {
                    "seed_count": full["execution"]["seed_count"],
                    "frame_start": full["source_window"]["frame_start"],
                    "frame_end": full["source_window"]["frame_end"],
                    "time_end_s": full["source_window"]["time_end_s"],
                    "resume_boundary_frame": full["execution"]["resume_policy"][
                        "recovery_point"
                    ],
                    "max_processes": full["resource_profile"]["max_concurrent_processes"],
                    "workers": full["resource_profile"]["cKDTree_workers"],
                },
                "reuse_policy": "old negative trace is binding-only; candidate output and state are new",
                "result_policy": "write immutable positive or negative receipt; right-censored/unknown remains zero credit",
                "qualification_effect": "none; even a completed canary does not itself set T2_macro or T2_path true",
            },
            "forbidden": [
                "rerun any old F3/F4 CFD input",
                "start solver or GPU",
                "submit or mutate a queue",
                "write matrix, registry, or ledger",
                "change unknown, CDF, reconstruction, event-window, or denominator rules",
                "drop unknown/right-censored seeds or grant partial credit",
                "expand to F3, a second F4 candidate, or a matrix",
            ],
        },
        "fixed_quality_gates": {
            "unknown_fraction_per_source_max": UNKNOWN_LIMIT,
            "f3_cdf_sup_abs_difference_max": CDF_LIMIT,
            "f4_event_window_required": True,
            "reconstruction_gate": ess32["fixed_gate"],
            "full_source_window_s": SOURCE_END_S,
            "right_censor_is_unknown": True,
            "no_partial_credit": True,
        },
        "execution_constraints": {
            "read_only_json_hash_closure": True,
            "source_h5_reopened_by_admission": False,
            "source_h5_rehashed_by_admission": False,
            "old_cfd_rerun": False,
            "solver_started": False,
            "gpu_started": False,
            "queue_mutation": 0,
            "matrix_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "qualification_credit": 0,
        },
        "hash_bindings": hash_bindings,
    }


def verify(path: Path = OUTPUT) -> dict[str, Any]:
    value = load(path)
    assert value["schema"] == "core.material.t2.f3_f4.admission.root_review_only.v1"
    for item in value["hash_bindings"].values():
        bound = LAB / item["path"]
        assert bound.is_file(), bound
        assert bound.stat().st_size == item["bytes"], bound
        assert sha256(bound) == item["sha256"], bound
    assert value["status"] == "proposal_only_root_review_required"
    assert value["T2_macro"] is False
    assert value["T2_path"] is False
    assert value["qualification_credit"] == "none"
    assert value["sole_future_authorization_boundary"]["authorized_now"] is False
    return value


def render_report(contract: dict[str, Any], contract_sha: str) -> str:
    f3 = contract["historical_audit"]["f3"]
    f4 = contract["historical_audit"]["f4"]
    selected = contract["selected_route"]
    lines = [
        "# F3/F4 宏观 T2 admission contract（root-review-only，2026-09-21）",
        "",
        "本产物只做 JSON/hash closure。没有重跑旧 CFD，没有启动 solver/GPU/queue，没有写 matrix、registry 或 ledger。",
        "",
        "## 当前资格状态",
        "",
        "F3 与 F4 的 T1 qualification receipt 都为 `T1_numerical=true`、`matrix_complete=true`，但两者都明确 `T2_macro=false`、`T2_path=false`。本合同不把既有 CPU/native、sidecar 或旧材料结果升级为 T2 credit。",
        "",
        f"F3 的两条完整 source/window 记录结构与质量闭合通过，但 fixed unknown 上限 `{UNKNOWN_LIMIT}` 和 CDF sup 上限 `{CDF_LIMIT}` 失败；最大 source unknown 为 `{f3['maximum_unknown_fraction']}`。F4 保留的 6 个材料 case 全部 event-window 不完整，unknown gate 全部失败，虽 mass closed=true。",
        "",
        "## 选择的最小候选",
        "",
        f"选择 `{selected['candidate_id']}`（F4 tallwall120 cell-14）作为唯一 deferred candidate。它绑定 T1-qualified 原生 source：1086 帧、217485 粒子、0–4.340002980805959 s，exact native rows，无 stride 或 synthetic cadence；已有固定 reconstruction/ESS/rank/anisotropy、unknown 和 event-window 合同。",
        "",
        "该候选不是已通过的材料结果：frame 40→41 的 128-seed counterfactual survivor 为 0，既有 bounded preflight 在 frame 41 后为 511/512 unknown、right-censored。它只能作为一次新的、独立 output stem 的诊断性 material sidecar proposal。",
        "",
        "## 唯一授权边界",
        "",
        "当前 `authorized_now=false`。若 root 明确授权，唯一允许的下一步是：在同一已绑定 T1 source 上执行一次 CPU-only、单进程、cKDTree workers=1 的 `f4_ess32_v2` full-source material sidecar，使用既有合同的新 output stem，覆盖 frame 0–1085 和完整 4.34 s 窗口，并从 frame 40 的 content-addressed checkpoint 恢复。",
        "",
        "该动作不重跑 CFD，不启动 solver/GPU/queue，不扩展 F3/F4 矩阵；旧负 trace 只能作为 binding input。所有 512 seeds 保留在分母中，unknown/right-censor 保持 unknown，任何失败都写 immutable negative receipt 并给 zero credit。即使 sidecar 完成，也不会单独把 `T2_macro` 或 `T2_path` 置为 true。",
        "",
        "禁止改变 unknown、CDF、reconstruction、event-window 或 denominator 门；禁止丢弃未知样本、插值伪造 cadence、重用旧 trace 状态或写入 matrix/registry/ledger。",
        "",
        f"合同：`{OUTPUT.relative_to(LAB)}`；SHA-256 `{contract_sha}`。",
        "",
        "## 绑定证据",
        "",
        "- F3/F4 CPU source-window audit：完整来源窗口与 reader/reconstruction integrity 通过，但科学门失败；qualification claim=none。",
        "- F4 macro sidecar preflight：sidecar provenance 通过，但不是独立 CFD；unknown/event/matrix gates 失败。",
        "- F4 ESS32 candidate/full-source contracts：固定门、完整来源窗口、资源预算、checkpoint/resume 和新 output stem 已 hash-bound；candidate 仍 proposal-only。",
        "- F3/F4 T1 qualification receipts：只证明 T1，不授予 T2。",
        "",
        "本合同的 T2 credit、registry mutation、ledger mutation 和 Core gate effect 均为 0/false。",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--report", type=Path, default=REPORT)
    args = parser.parse_args(argv)
    output = Path(args.output).resolve()
    report = Path(args.report).resolve()
    if output.exists():
        raise FileExistsError(f"immutable contract already exists: {output}")
    contract = build_contract()
    output.parent.mkdir(parents=True, exist_ok=True)
    report.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report.write_text(
        render_report(contract, sha256(output)),
        encoding="utf-8",
    )
    print(output)
    print(report)
    print(sha256(output))
    print(sha256(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
