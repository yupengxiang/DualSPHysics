#!/usr/bin/env python3
"""Perform an independent, read-only root review of the deferred F4 ESS32 canary.

The review validates the existing full-source contract and its small JSON
bindings.  The registered frame-40->41 ESS32 counterfactual has zero
survivors, so this receipt deliberately remains proposal-only and does not
authorize a sidecar.  No HDF5 is opened or rehashed, and no CFD, solver, GPU,
queue, matrix, ledger, or registry operation is available here.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
FULL_CONTRACT = LAB / (
    "campaigns/core-v1/material/evidence/"
    "f4-tallwall120-native-cell14-f4-ess32-full-source-canary-contract-20260921.json"
)
CANDIDATE_CONTRACT = LAB / (
    "campaigns/core-v1/material/evidence/"
    "f4-tallwall120-native-cell14-candidate-contract-20260921.json"
)
PREFLIGHT = LAB / (
    "campaigns/core-v1/material/evidence/"
    "f4-tallwall120-native-cell14-material-preflight-20260921.json"
)
ROOT_CAUSE = LAB / (
    "campaigns/core-v1/material/evidence/"
    "f4-tallwall120-native-cell14-root-cause-audit-20260921.json"
)
SOURCE_WINDOW_AUDIT = LAB / (
    "campaigns/core-v1/material/evidence/"
    "f3-f4-t2-cpu-source-window-audit-v1-20260920.json"
)
PRIOR_ADMISSION = LAB / (
    "campaigns/core-v1/material/evidence/"
    "f3-f4-t2-admission-root-review-contract-20260921.json"
)
OLD_IMPLEMENTATION = LAB / "scripts/f4_tallwall120_full_source_canary_contract_v1.py"
OUTPUT = LAB / (
    "campaigns/core-v1/material/evidence/"
    "f4-tallwall120-native-cell14-f4-ess32-root-review-20260921.json"
)
REPORT = LAB / "reports/F4-ESS32-ROOT-REVIEW-2026-09-21.zh-CN.md"

SOURCE_SHA256 = "91846866c177e4c3036b7ef92c33a4e0bde7d9e8993efb01dde300811b7c096e"
SOURCE_PATH = (
    "campaigns/core-v1/cfd/f4-tallwall120-archives-v2/"
    "f4-tallwall120-qualification-cell-14/product/trajectory.h5"
)
SOURCE_FRAMES = 1086
SOURCE_PARTICLES = 217485
SOURCE_END_S = 4.340002980805959
UNKNOWN_LIMIT = 0.01
OLD_IMPLEMENTATION_SHA256 = "9b327940cfe7bc1919534ed78d5c1fd1cac3e87db4191f81b6a60e8adf11e29e"


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


def verify_existing_binding(record: dict[str, Any]) -> dict[str, Any]:
    path = Path(record["path"]).resolve()
    assert path.is_file(), path
    assert sha256(path) == record["sha256"], path
    return {
        "path": rel(path),
        "sha256": record["sha256"],
        "bytes": path.stat().st_size,
        "role": record.get("role", "existing contract binding"),
    }


def build_review() -> dict[str, Any]:
    full = load(FULL_CONTRACT)
    candidate = load(CANDIDATE_CONTRACT)
    preflight = load(PREFLIGHT)
    root_cause = load(ROOT_CAUSE)
    source_window_audit = load(SOURCE_WINDOW_AUDIT)
    prior_admission = load(PRIOR_ADMISSION)

    assert full["schema"] == "core.material.f4.tallwall120.full_source_canary_contract.v1"
    assert full["status"] == "proposal_only_deferred_after_one_transition_failure"
    assert full["route_decision"]["automatic_execution"] is False
    assert full["route_decision"]["decision"] == "deferred"
    assert full["candidate"]["candidate_id"] == "f4_ess32_v2"
    assert full["candidate"]["qualification_credit"] == "none"
    assert full["candidate"]["qualification_status"] == "proposal_only"
    assert full["candidate"]["unknown_fraction_limit"] == UNKNOWN_LIMIT
    assert full["candidate"]["event_gate_changed"] is False
    assert full["candidate"]["cdf_changed"] is False
    counterfactual = full["candidate"]["one_transition_counterfactual"]
    assert counterfactual["frame_transition"] == "40->41"
    assert counterfactual["counterfactual_cohort_survivors"] == 0
    assert counterfactual["credit"].startswith("none")

    window = full["source_window"]
    source = window["source"]
    assert source["sha256"] == SOURCE_SHA256
    assert window["frame_start"] == 0
    assert window["frame_end"] == SOURCE_FRAMES - 1
    assert window["frame_count"] == SOURCE_FRAMES
    assert window["particle_count"] == SOURCE_PARTICLES
    assert window["time_end_s"] == SOURCE_END_S
    assert window["native_rows_exact"] is True
    assert window["no_stride_or_synthetic_cadence"] is True
    assert window["event_unknown_policy"] == "NaN/right-censored; no saved-chord imputation"
    source_path = Path(source["path"])
    assert source_path.is_file()

    candidate_ess32 = candidate["contracts"]["f4_ess32_v2"]
    assert candidate["schema"] == "core.material.f4.tallwall120.candidate_contract.v1"
    assert candidate["source_sha256"] == SOURCE_SHA256
    assert candidate_ess32["backend"] == "f4_ckdtree_visible_shepard_ess32_v2"
    assert candidate_ess32["neighbours"] == 32
    assert candidate_ess32["unknown_fraction_limit"] == UNKNOWN_LIMIT
    assert candidate_ess32["unknown_gate_changed"] is False
    assert candidate_ess32["event_gate_changed"] is False
    assert candidate_ess32["cdf_changed"] is False
    assert candidate["candidate_evaluation"]["f4_ess32_v2"][
        "counterfactual_cohort_survivors"
    ] == 0

    assert preflight["schema"] == "core.material.f4.tallwall120.cpu_preflight.v1"
    assert preflight["qualification"]["T2_macro"] is False
    assert preflight["qualification"]["T2_path"] is False
    assert preflight["qualification"]["qualification_credit"] == "none"
    assert preflight["gate_evaluation"]["unknown_fraction"] == 0.998046875
    assert preflight["gate_evaluation"]["unknown_gate_limit"] == UNKNOWN_LIMIT
    assert preflight["gate_evaluation"]["event_window_complete"] is False
    assert preflight["gate_evaluation"]["right_censored"] is True
    assert preflight["execution_constraints"]["scientific_denominator_changed"] is False
    assert preflight["execution_constraints"]["thresholds_changed"] is False

    assert root_cause["qualification"]["T2_macro"] is False
    assert root_cause["qualification"]["T2_path"] is False
    assert root_cause["qualification"]["qualification_credit"] == "none"
    assert source_window_audit["gate_evaluation"]["T2_macro"] is False
    assert source_window_audit["gate_evaluation"]["T2_path"] is False
    assert source_window_audit["gate_evaluation"]["qualification_credit"] == "none"
    assert prior_admission["T2_macro"] is False
    assert prior_admission["T2_path"] is False
    assert prior_admission["qualification_credit"] == "none"

    planned_artifacts = full["execution"]["planned_artifacts"]
    output_stem = Path(full["execution"]["output_stem"])
    assert full["execution"]["output_stem_is_new"] is True
    assert not output_stem.exists()
    artifact_absence = {
        name: {"path": str(Path(path)), "exists": Path(path).exists()}
        for name, path in planned_artifacts.items()
    }
    assert all(item["exists"] is False for item in artifact_absence.values())
    assert full["execution"]["existing_trace_reuse"]["binding_only"] is True
    assert full["execution"]["existing_trace_reuse"]["candidate_output_reuse"] is False

    old_implementation_sha = sha256(OLD_IMPLEMENTATION)
    assert old_implementation_sha == OLD_IMPLEMENTATION_SHA256
    existing_bindings = {
        key: verify_existing_binding(value)
        for key, value in full["hash_bindings"].items()
        if isinstance(value, dict) and "path" in value
    }

    hash_bindings = {
        "full_source_contract": bind(FULL_CONTRACT, "deferred ESS32 full-source contract"),
        "candidate_contract": bind(CANDIDATE_CONTRACT, "ESS32 candidate contract"),
        "negative_material_preflight": bind(PREFLIGHT, "negative bounded material preflight"),
        "root_cause_audit": bind(ROOT_CAUSE, "first-failure root-cause audit"),
        "source_window_audit": bind(SOURCE_WINDOW_AUDIT, "F3/F4 source-window audit"),
        "prior_t2_admission": bind(PRIOR_ADMISSION, "prior F3/F4 T2 admission contract"),
        "old_contract_implementation": bind(
            OLD_IMPLEMENTATION, "existing full-source contract implementation"
        ),
        "implementation": bind(Path(__file__), "independent ESS32 root-review implementation"),
        "test": bind(
            LAB / "tests/test_f4_ess32_root_review_v1.py",
            "independent ESS32 root-review regression test",
        ),
    }

    return {
        "schema": "core.material.f4.ess32.root_review_receipt.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "record_id": "f4-tallwall120-cell14-f4-ess32-root-review-20260921",
        "status": "proposal_only_blocked_by_zero_counterfactual_survivor",
        "review_decision": {
            "candidate_id": "f4_ess32_v2",
            "authorized_one_cpu_only": False,
            "automatic_execution": False,
            "reason": (
                "the registered frame-40->41 ESS32 counterfactual has zero survivors; "
                "the existing contract therefore requires candidate implementation review "
                "before any full-source sidecar authorization"
            ),
            "reopen_condition": (
                "new versioned candidate implementation and hash-bound root review; "
                "do not authorize this unchanged zero-survivor proposal"
            ),
        },
        "source_window_review": {
            "path": SOURCE_PATH,
            "sha256": SOURCE_SHA256,
            "source_exists": source_path.is_file(),
            "hdf5_opened_by_this_review": False,
            "hdf5_rehashed_by_this_review": False,
            "frame_start": window["frame_start"],
            "frame_end": window["frame_end"],
            "frame_count": window["frame_count"],
            "particle_count": window["particle_count"],
            "time_end_s": window["time_end_s"],
            "native_rows_exact": window["native_rows_exact"],
            "no_stride_or_synthetic_cadence": window["no_stride_or_synthetic_cadence"],
            "source_binding_consistent": True,
        },
        "contract_hash_review": {
            "full_contract_status": full["status"],
            "existing_small_json_bindings_verified": True,
            "verified_existing_bindings": existing_bindings,
            "old_implementation_sha256": old_implementation_sha,
            "old_implementation_sha256_matches_contract": True,
            "output_stem": full["execution"]["output_stem"],
            "output_stem_is_absent": not output_stem.exists(),
            "planned_artifacts_absent": artifact_absence,
        },
        "fixed_zero_credit_rules": {
            "unknown_fraction_limit": UNKNOWN_LIMIT,
            "unknown_or_right_censored_is_unknown": True,
            "no_partial_credit": True,
            "event_window_required": True,
            "cdf_changed": False,
            "event_gate_changed": False,
            "denominator_changed": False,
            "historical_preflight_unknown_fraction": preflight["gate_evaluation"][
                "unknown_fraction"
            ],
            "historical_preflight_event_window_complete": preflight["gate_evaluation"][
                "event_window_complete"
            ],
            "qualification_credit": "none",
            "T2_macro": False,
            "T2_path": False,
        },
        "candidate_quality_contract": {
            "backend": candidate_ess32["backend"],
            "neighbours": candidate_ess32["neighbours"],
            "fixed_gate": candidate_ess32["fixed_gate"],
            "regularization_m": candidate_ess32["regularization_m"],
            "maximum_support_distance_m": candidate_ess32["maximum_support_distance_m"],
            "frame_transition": counterfactual["frame_transition"],
            "counterfactual_cohort_survivors": counterfactual[
                "counterfactual_cohort_survivors"
            ],
            "qualification_status": "proposal_only",
        },
        "future_boundary_if_reopened": {
            "action": "one CPU-only material sidecar only",
            "seed_count": full["execution"]["seed_count"],
            "frame_start": window["frame_start"],
            "frame_end": window["frame_end"],
            "resume_boundary_frame": full["execution"]["resume_policy"]["recovery_point"],
            "output_stem": full["execution"]["output_stem"],
            "workers": full["resource_profile"]["cKDTree_workers"],
            "max_concurrent_processes": full["resource_profile"]["max_concurrent_processes"],
            "authorization_required": True,
            "does_not_authorize_now": True,
        },
        "forbidden_actions": [
            "rerun old CFD or any solver",
            "start GPU work",
            "submit or mutate queue",
            "write matrix, ledger, or registry",
            "change unknown, reconstruction, CDF, event, cadence, or denominator rules",
            "drop unknown/right-censored seeds or grant partial credit",
            "reuse old negative trace state as candidate state",
        ],
        "execution_constraints": {
            "read_only_json_review": True,
            "sidecar_started": False,
            "old_cfd_rerun": False,
            "solver_started": False,
            "gpu_started": False,
            "queue_mutation": 0,
            "matrix_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "qualification_credit": 0,
            "core_gate_changed": False,
        },
        "hash_bindings": hash_bindings,
    }


def verify(path: Path = OUTPUT) -> dict[str, Any]:
    value = load(path)
    assert value["schema"] == "core.material.f4.ess32.root_review_receipt.v1"
    for item in value["hash_bindings"].values():
        bound = LAB / item["path"]
        assert bound.is_file(), bound
        assert bound.stat().st_size == item["bytes"], bound
        assert sha256(bound) == item["sha256"], bound
    assert value["review_decision"]["authorized_one_cpu_only"] is False
    assert value["candidate_quality_contract"]["counterfactual_cohort_survivors"] == 0
    assert value["fixed_zero_credit_rules"]["qualification_credit"] == "none"
    return value


def render_report(review: dict[str, Any], review_sha: str) -> str:
    lines = [
        "# F4 f4_ess32_v2 独立 root review（2026-09-21）",
        "",
        "结论：`proposal_only_blocked_by_zero_counterfactual_survivor`。本次只读验证现有合同与 JSON hash closure，没有启动 sidecar。",
        "",
        "## 阻断原因",
        "",
        "已有 ESS32 合同的 frame 40→41 counterfactual cohort survivor 为 `0`。既有合同本身因此标记 `deferred`，要求先完成新的 candidate implementation review；当前没有足够证据把这个未验证实现授权为 full-source sidecar。该判断不修改任何质量门，也不把失败材料结果升级成 T2。",
        "",
        "## 来源窗口与合同核验",
        "",
        "T1 source binding 为 1086 个 native frames、217485 particles、0–4.340002980805959 s，exact native rows，无 stride/synthetic cadence。source SHA、candidate/preflight/root-cause/旧 admission JSON 及旧合同实现 SHA 均通过核验；目标 output stem 与全部 planned artifacts 均不存在。此 review 没有打开或重新哈希 HDF5。",
        "",
        "## 固定门与授权边界",
        "",
        "unknown 上限继续为 `0.01`，right-censor 保持 unknown，event window 必须完整，禁止 partial credit。已有 bounded preflight 为 `511/512 = 0.998046875` unknown 且 right-censored，T2 macro/path 均为 false。",
        "",
        "当前 `authorized_one_cpu_only=false`。若未来产生新的、版本化且 hash-bound 的 candidate implementation，并再次通过 root review，届时最多只能授权一次 CPU-only、单进程、512-seed、frame 0–1085 的 material sidecar；禁止 CFD/solver/GPU/queue/ledger/registry/matrix。",
        "",
        "本次不生成 sidecar、不写入输出前缀、不改变 denominator、threshold、Core gate 或历史负证据。",
        "",
        f"新 review receipt：`{OUTPUT.relative_to(LAB)}`；SHA-256 `{review_sha}`。",
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
        raise FileExistsError(f"immutable review already exists: {output}")
    review = build_review()
    output.parent.mkdir(parents=True, exist_ok=True)
    report.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(review, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report.write_text(render_report(review, sha256(output)), encoding="utf-8")
    print(output)
    print(report)
    print(sha256(output))
    print(sha256(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
