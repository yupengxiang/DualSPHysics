#!/usr/bin/env python3
"""Register the bounded B2 learning evidence without relabeling it as qualified.

The independent R3-G4 sidecar already contains a complete three-seed run for
the local-message route and the physics-residual hybrid route.  B2 consumes
those immutable candidate-only artifacts, verifies their hashes and causal
input declarations, and joins them with the A1 oracle/failure profile.  It
does not reuse the weights as a qualification claim and does not launch a new
training attempt merely to inflate the L2 counter.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics

try:
    from scripts.l2_campaign import (
        CAMPAIGN,
        LAB,
        atomic_json,
        read_json,
        require_adopted,
        update_stage,
        update_usage,
        utc_now,
    )
except ModuleNotFoundError:
    from l2_campaign import (
        CAMPAIGN,
        LAB,
        atomic_json,
        read_json,
        require_adopted,
        update_stage,
        update_usage,
        utc_now,
    )


SOURCE_ROOT = LAB / "experiments" / "r3-g4-baseline-routes"
RUN_MANIFEST = SOURCE_ROOT / "run_manifest.json"
AUDIT_PATH = SOURCE_ROOT / "audit.json"
REPORT_PATH = CAMPAIGN / "reports" / "b2-learning-baseline.json"
MARKDOWN_PATH = CAMPAIGN / "reports" / "b2-learning-baseline.md"
ROUTES = ("local_interaction", "physics_residual")
SEEDS = (17, 29, 43)
TEST_METRICS = (
    "learned_rmse_over_dp",
    "learned_ade_m",
    "learned_fde_m",
    "learned_velocity_rmse_mps",
    "learned_com_rmse_m",
    "constant_velocity_rmse_over_dp",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def repo_relative(path: Path) -> str:
    return path.resolve().relative_to(LAB.resolve()).as_posix()


def finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == value and abs(float(value)) != float("inf")


def result_summary(run: dict) -> dict:
    output = (LAB / run["output"]).resolve()
    checkpoint = (LAB / run["checkpoint"]).resolve()
    log = (LAB / run["log"]).resolve()
    if not output.is_file() or not checkpoint.is_file() or not log.is_file():
        raise FileNotFoundError(f"B2 source artifact missing for {run['route']} seed {run['seed']}")
    result = read_json(output)
    rollouts = result.get("test_rollout", {})
    if set(rollouts) != {"F1_twin_obstacle", "W06_standard_fast_center", "F3_transverse_slosh"}:
        raise ValueError(f"unexpected B2 test cases in {output}")
    status_counts = {case_id: row.get("status") for case_id, row in rollouts.items()}
    finite_counts = {
        metric: sum(finite(row.get(metric)) for row in rollouts.values())
        for metric in TEST_METRICS
    }
    input_contract = result.get("input_contract", {})
    prohibited = input_contract.get("prohibited_rollout_inputs", [])
    causal_ok = (
        isinstance(prohibited, list)
        and set(prohibited) >= {
            "future reference position",
            "future reference velocity",
            "future reference density",
            "future free-body trajectory",
        }
        and "current predicted state" in input_contract.get("prefix_invariance", "")
        and "current control" in input_contract.get("prefix_invariance", "")
    )
    return {
        "route": run["route"],
        "seed": int(run["seed"]),
        "source_run_status": run.get("status"),
        "returncode": run.get("returncode"),
        "physical_gpu_index": run.get("physical_gpu_index"),
        "gpu_uuid": (run.get("gpu") or {}).get("uuid"),
        "elapsed_seconds": run.get("elapsed_seconds"),
        "training_seconds": result.get("training_seconds"),
        "inference_seconds": result.get("inference_seconds"),
        "epochs_requested": result.get("epochs_requested"),
        "epochs_run": result.get("epochs_run"),
        "parameter_count": result.get("parameter_count"),
        "feature_width": result.get("feature_width"),
        "test_rollout_statuses": status_counts,
        "test_rollout_completed_count": sum(value == "completed" for value in status_counts.values()),
        "test_rollout_expected_count": len(rollouts),
        "finite_metric_counts": finite_counts,
        "test_rollouts": {
            case_id: {metric: row.get(metric) for metric in TEST_METRICS}
            for case_id, row in rollouts.items()
        },
        "input_contract": {
            "prefix_invariance": input_contract.get("prefix_invariance"),
            "prohibited_rollout_inputs": prohibited,
            "causal_check_pass": causal_ok,
        },
        "clipping": result.get("clipping"),
        "limitations": result.get("limitations"),
        "source_artifacts": {
            "result": {"path": repo_relative(output), "sha256": sha256(output), "bytes": output.stat().st_size},
            "checkpoint": {"path": repo_relative(checkpoint), "sha256": sha256(checkpoint), "bytes": checkpoint.stat().st_size},
            "log": {"path": repo_relative(log), "sha256": sha256(log), "bytes": log.stat().st_size},
        },
    }


def aggregate_route(records: list[dict]) -> dict:
    per_seed = []
    for record in records:
        values = [
            float(row["learned_rmse_over_dp"])
            for row in record["test_rollouts"].values()
            if finite(row.get("learned_rmse_over_dp"))
        ]
        per_seed.append({"seed": record["seed"], "test_macro_mean_rmse_over_dp": statistics.fmean(values) if values else None})
    values = [row["test_macro_mean_rmse_over_dp"] for row in per_seed if row["test_macro_mean_rmse_over_dp"] is not None]
    return {
        "seed_count": len(records),
        "seeds": sorted(record["seed"] for record in records),
        "seed_complete": len(records) == len(SEEDS),
        "test_rollout_completed_count": sum(record["test_rollout_completed_count"] for record in records),
        "test_rollout_expected_count": sum(record["test_rollout_expected_count"] for record in records),
        "per_seed_test_macro_mean_rmse_over_dp": per_seed,
        "macro_mean_over_seeds": statistics.fmean(values) if values else None,
        "macro_sample_std_over_seeds": statistics.stdev(values) if len(values) > 1 else None,
        "wall_or_physical_pass": "not_assessed_by_this_candidate_pilot",
    }


def build_report() -> dict:
    state = require_adopted()
    if state["stages"]["A1"]["status"] not in {"complete", "complete_with_findings"}:
        raise RuntimeError("B2 requires A1 to be complete")
    if state["stages"]["B2"]["status"] not in {"ready", "pending"}:
        raise RuntimeError("B2 already has a terminal status")
    run_manifest = read_json(RUN_MANIFEST)
    audit = read_json(AUDIT_PATH)
    if run_manifest.get("status") != "complete" or run_manifest.get("formal_ready") is not False:
        raise ValueError("B2 source run manifest is not explicitly candidate-only complete")
    if audit.get("status") != "complete" or not audit.get("checks", {}).get("candidate_only_not_formal"):
        raise ValueError("B2 source audit does not prove candidate-only scope")
    if tuple(run_manifest.get("routes", ())) != ROUTES or tuple(run_manifest.get("seeds", ())) != SEEDS:
        raise ValueError("B2 source matrix is not the declared two-route three-seed matrix")

    records = [result_summary(run) for run in run_manifest["runs"]]
    expected = {(route, seed) for route in ROUTES for seed in SEEDS}
    found = {(record["route"], record["seed"]) for record in records}
    if found != expected or len(records) != len(expected):
        raise ValueError(f"B2 seed matrix mismatch: found={sorted(found)}")
    if any(record["source_run_status"] != "completed" for record in records):
        raise ValueError("B2 has a non-completed source worker")
    if any(record["test_rollout_completed_count"] != record["test_rollout_expected_count"] for record in records):
        raise ValueError("B2 has an incomplete evaluation rollout")
    if any(not record["input_contract"]["causal_check_pass"] for record in records):
        raise ValueError("B2 causal input contract check failed")

    a1 = read_json(CAMPAIGN / "reports" / "a1-model-failure-diagnostics.json")
    route_records = {route: [record for record in records if record["route"] == route] for route in ROUTES}
    started = datetime.now(timezone.utc).isoformat()
    report = {
        "schema": "l2.b2.learning_baseline.v1",
        "stage": "B2",
        "created_at_utc": started,
        "baseline_commit": state["baseline_commit"],
        "status": "complete_with_findings",
        "decision": "candidate_only_routes_registered; no model_or_data_qualification",
        "scope": {
            "data_role": "development",
            "statistical_unit": "independent physical case; seed is a second-level replicate",
            "source_policy": "read-only registration of an independent candidate-only three-seed rerun",
            "new_training_attempts_in_L2": 0,
            "model_success_required_for_B2_exit": False,
        },
        "tracks": {
            "raw_learned_dynamics": {
                "route": "local_interaction",
                "description": "direct displacement predictor with current local inverse-distance message summary and current boundary features; no posthoc wall projection",
                "seeds": list(SEEDS),
            },
            "constrained_or_hybrid": {
                "route": "physics_residual",
                "description": "normalized acceleration residual integrated with the current velocity state; explicit physical update prior, no hidden wall projection",
                "seeds": list(SEEDS),
            },
        },
        "source_contract": {
            "run_manifest": {"path": repo_relative(RUN_MANIFEST), "sha256": sha256(RUN_MANIFEST)},
            "route_audit": {"path": repo_relative(AUDIT_PATH), "sha256": sha256(AUDIT_PATH)},
            "release_manifest": {"path": "release/v0.1-development/manifest.json", "sha256": sha256(LAB / "release/v0.1-development/manifest.json")},
            "run_budget": run_manifest.get("budget"),
            "candidate_only": True,
        },
        "runs": records,
        "route_summary": {route: aggregate_route(route_records[route]) for route in ROUTES},
        "oracle_and_failure_diagnostics": {
            "a1_report": "reports/a1-model-failure-diagnostics.json",
            "oracle_diagnostics": a1["oracle_diagnostics"],
            "failure_profile": a1["failure_profile"],
            "legacy_route_summary": a1["route_summary"],
            "failure_aware_metrics_preserved": True,
        },
        "acceptance": {
            "two_declared_tracks": True,
            "three_seeds_per_track": all(aggregate_route(route_records[route])["seed_complete"] for route in ROUTES),
            "all_six_workers_completed": True,
            "all_eighteen_candidate_test_rollouts_completed": all(
                record["test_rollout_completed_count"] == 3 for record in records
            ),
            "causal_input_contract_checked": True,
            "future_fluid_or_body_state_used": False,
            "failure_aware_metrics_included": True,
            "wall_contact_physical_pass_claimed": False,
            "formal_model_qualification_claimed": False,
            "formal_data_release_claimed": False,
        },
        "limitations": [
            "candidate-only development pilot; no formal model ranking or family qualification",
            "route outputs are finite rollout diagnostics, not a wall-contact pass",
            "material transport, density/pressure prediction, free-body coupling, and T2/T3/T4 are not assessed",
            "the source run predates L2 adoption; L2 registers it read-only and does not count its historical GPU time",
        ],
        "resource_observation": {
            "new_training_attempts": 0,
            "new_storage_bytes": 0,
            "historical_source_gpu_hours_not_charged_to_L2": sum(float(run.get("elapsed_seconds", 0.0)) for run in run_manifest["runs"]) / 3600.0,
        },
    }
    return report


def markdown(report: dict) -> str:
    lines = [
        "# B2 学习基线登记",
        "",
        "结论：登记了两个三种子开发轨道，但没有模型资格化或数据发布声明。",
        "",
        "| 轨道 | 路线 | seeds | 测试 rollout | 跨 seed 宏平均 RMSE/dp |",
        "|---|---|---:|---:|---:|",
    ]
    for label, route in (("raw learned dynamics", "local_interaction"), ("constrained/hybrid", "physics_residual")):
        summary = report["route_summary"][route]
        lines.append(
            f"| {label} | `{route}` | {summary['seed_count']} | "
            f"{summary['test_rollout_completed_count']}/{summary['test_rollout_expected_count']} | "
            f"{summary['macro_mean_over_seeds']:.4f} ± {summary['macro_sample_std_over_seeds']:.4f} |"
        )
    lines.extend([
        "",
        "- 输入因果审计通过：只允许当前预测状态、当前控制、当前边界摘要和初始属性；不读未来流体/刚体状态。",
        "- A1 的 96 case-run 失败曲线、oracle 误差和有限/穿墙分类被原样保留。",
        "- 这些结果仍是 development/candidate-only；没有墙面物理通过、T2/T3/T4 或正式模型资格结论。",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    report = build_report()
    atomic_json(REPORT_PATH, report)
    MARKDOWN_PATH.parent.mkdir(parents=True, exist_ok=True)
    MARKDOWN_PATH.write_text(markdown(report))
    report["resource_observation"]["new_storage_bytes"] = REPORT_PATH.stat().st_size + MARKDOWN_PATH.stat().st_size
    atomic_json(REPORT_PATH, report)
    update_usage(new_storage_bytes=report["resource_observation"]["new_storage_bytes"])
    update_stage("B2", "complete", facts={
        "report": "reports/b2-learning-baseline.json",
        "markdown": "reports/b2-learning-baseline.md",
        "decision": report["decision"],
        "seed_complete_tracks": 2,
        "model_physical_pass_count": 0,
        "new_training_attempts": 0,
    })
    print(json.dumps({
        "status": report["status"],
        "decision": report["decision"],
        "report": str(REPORT_PATH),
        "markdown": str(MARKDOWN_PATH),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
