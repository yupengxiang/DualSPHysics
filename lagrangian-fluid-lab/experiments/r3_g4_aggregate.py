#!/usr/bin/env python3
"""Aggregate R3 G4 baseline runs without turning model failure into a gate."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np


ROUTES = ("particle_mlp", "deepset_context", "local_interaction", "physics_residual")
SEEDS = (17, 29, 43)
LAB = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = LAB / "campaigns" / "v0.1-candidate" / "w00-inventory.json"


def mean_std(values: list[float | None]) -> dict[str, Any]:
    finite = np.asarray([value for value in values if value is not None and np.isfinite(value)], dtype=float)
    return {
        "mean": float(finite.mean()) if len(finite) else None,
        "sample_std": float(finite.std(ddof=1)) if len(finite) > 1 else 0.0 if len(finite) else None,
        "values": finite.tolist(),
        "n": int(len(finite)),
    }


def bootstrap_cases(values: list[float], seed: int = 20260907, draws: int = 2000) -> dict[str, Any]:
    values = np.asarray(values, dtype=float)
    if not len(values):
        return {"estimate": None, "q025": None, "q975": None, "cases": 0, "draws": draws}
    rng = np.random.default_rng(seed)
    sampled = values[rng.integers(0, len(values), size=(draws, len(values)))].mean(axis=1)
    return {
        "estimate": float(values.mean()), "q025": float(np.quantile(sampled, 0.025)),
        "q975": float(np.quantile(sampled, 0.975)), "cases": int(len(values)), "draws": draws,
        "resampling_unit": "independent physical case, not frame",
    }


def _resolve_artifact(value: str | Path, lab_root: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else lab_root / path


def load_runs(results_dir: Path, run_manifest: dict[str, Any] | None = None,
              lab_root: Path | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    """Load only artifacts named by the run manifest, never stale directory files."""
    if run_manifest is None:
        return [json.loads(path.read_text()) for path in sorted(results_dir.glob("*.json"))], []
    lab_root = Path(lab_root or LAB).resolve()
    expected_dir = Path(results_dir).resolve()
    runs = []
    issues = []
    seen_paths = set()
    for entry in run_manifest.get("runs", []):
        output = entry.get("output")
        if not output:
            issues.append(f"missing output path for {entry.get('route')} seed {entry.get('seed')}")
            continue
        path = _resolve_artifact(output, lab_root).resolve()
        if path.parent != expected_dir:
            issues.append(f"result artifact is outside results directory: {path}")
            continue
        if path in seen_paths:
            issues.append(f"duplicate output path: {path}")
            continue
        seen_paths.add(path)
        if not path.is_file():
            issues.append(f"missing result artifact: {path}")
            continue
        try:
            result = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as error:
            issues.append(f"unreadable result artifact {path}: {error}")
            continue
        if result.get("route") != entry.get("route") or int(result.get("seed", -1)) != int(entry.get("seed", -2)):
            issues.append(f"result provenance mismatch: {path}")
            continue
        if entry.get("status") != "completed":
            issues.append(f"manifest entry is not completed: {entry.get('route')} seed {entry.get('seed')}")
            continue
        result["_manifest_output"] = str(path)
        runs.append(result)
    return runs, issues


def audit_gpu_manifest(run_manifest: dict[str, Any], config: dict[str, Any],
                       inventory: dict[str, Any], expected: list[tuple[str, int]]) -> dict[str, Any]:
    """Validate physical index, UUID mapping, status, and route/seed uniqueness."""
    allowed_indices = {int(value) for value in config.get("allowed_gpu_indices", [])}
    allowed_uuids = set(inventory.get("execution_policy", {}).get("allowed_gpu_uuids", []))
    inventory_map = {
        int(gpu["physical_index"]): gpu.get("uuid")
        for gpu in inventory.get("host", {}).get("gpus", [])
        if "physical_index" in gpu
    }
    entries = run_manifest.get("runs", [])
    combinations = []
    issues = []
    for entry in entries:
        route = entry.get("route")
        seed = entry.get("seed")
        combination = (route, int(seed)) if route is not None and seed is not None else None
        if combination is not None:
            combinations.append(combination)
        index = entry.get("physical_gpu_index")
        uuid = entry.get("gpu_uuid")
        if entry.get("status") != "completed":
            issues.append(f"incomplete run entry: {route} seed {seed}")
        if index is None or int(index) not in allowed_indices:
            issues.append(f"GPU index outside allowlist: {index}")
        else:
            expected_uuid = inventory_map.get(int(index))
            if uuid != expected_uuid:
                issues.append(f"GPU UUID/index mismatch: index={index} uuid={uuid} expected={expected_uuid}")
        if uuid not in allowed_uuids:
            issues.append(f"GPU UUID outside allowlist: {uuid}")
    expected_set = set(expected)
    return {
        "pass": run_manifest.get("status") == "complete"
        and len(entries) == len(expected)
        and sorted(combinations) == sorted(expected)
        and len(set(combinations)) == len(combinations)
        and not issues,
        "issues": issues,
        "entry_count": len(entries),
        "expected_count": len(expected),
        "combinations": [list(item) for item in sorted(combinations)],
        "expected_combinations": [list(item) for item in sorted(expected_set)],
        "allowed_indices": sorted(allowed_indices),
        "allowed_uuids": sorted(allowed_uuids),
    }


def aggregate_route(route: str, runs: list[dict[str, Any]]) -> dict[str, Any]:
    route_runs = [run for run in runs if run.get("route") == route]
    combinations = [(int(run["seed"]), run.get("route")) for run in route_runs]
    case_ids = sorted({case_id for run in route_runs for case_id in run.get("test_rollout", {})})
    per_case = {}
    for case_id in case_ids:
        entries = [run["test_rollout"][case_id] for run in route_runs if case_id in run.get("test_rollout", {})]
        first = entries[0]
        per_case[case_id] = {
            "family": first["family"], "background_id": first["background_id"], "split": first["split"],
            "seeds": sorted(int(run["seed"]) for run in route_runs if case_id in run.get("test_rollout", {})),
            "status_by_seed": {str(run["seed"]): run["test_rollout"][case_id]["status"] for run in route_runs if case_id in run.get("test_rollout", {})},
            "learned_position_rmse_over_dp": mean_std([entry.get("learned_rmse_over_dp") for entry in entries]),
            "learned_ade_m": mean_std([entry.get("learned_ade_m") for entry in entries]),
            "learned_fde_m": mean_std([entry.get("learned_fde_m") for entry in entries]),
            "learned_velocity_rmse_mps": mean_std([entry.get("learned_velocity_rmse_mps") for entry in entries]),
            "learned_com_rmse_m": mean_std([entry.get("learned_com_rmse_m") for entry in entries]),
            "output_saturation_fraction": mean_std([entry.get("output_saturation_fraction") for entry in entries]),
            "constant_velocity_position_rmse_over_dp": entries[0].get("constant_velocity_rmse_over_dp"),
            "constant_velocity_position_fde_m": entries[0].get("constant_velocity_fde_m"),
            "degradation_ratio_vs_constant": (
                float(np.mean([entry["learned_rmse_over_dp"] for entry in entries]) / entries[0]["constant_velocity_rmse_over_dp"])
                if entries[0].get("constant_velocity_rmse_over_dp") not in (None, 0)
                and all(entry.get("learned_rmse_over_dp") is not None for entry in entries) else None
            ),
            "control_sources": sorted({entry.get("control_source") for entry in entries}),
            "boundary_sources": sorted({entry.get("boundary_source") for entry in entries}),
            "boundary_available": all(bool(entry.get("boundary_available")) for entry in entries),
            "mass_identity_preserved": all(bool(entry.get("mass_identity_preserved")) for entry in entries),
        }
    def macro(metric: str) -> dict[str, Any]:
        values = [per_case[case][metric]["mean"] for case in case_ids if per_case[case][metric]["mean"] is not None]
        return {"case_values": values, "bootstrap": bootstrap_cases(values)}
    family_cases: dict[str, list[str]] = defaultdict(list)
    background_cases: dict[str, list[str]] = defaultdict(list)
    for case_id, value in per_case.items():
        family_cases[value["family"]].append(case_id)
        background_cases[value["background_id"]].append(case_id)
    per_family = {
        family: {"case_ids": sorted(ids), "position_rmse_over_dp": bootstrap_cases([per_case[c]["learned_position_rmse_over_dp"]["mean"] for c in ids])}
        for family, ids in sorted(family_cases.items())
    }
    per_background = {
        background: {"case_ids": sorted(ids), "position_rmse_over_dp": bootstrap_cases([per_case[c]["learned_position_rmse_over_dp"]["mean"] for c in ids])}
        for background, ids in sorted(background_cases.items())
    }
    return {
        "route": route, "run_count": len(route_runs), "seeds": sorted(int(run["seed"]) for run in route_runs),
        "route_seed_combinations": [list(item) for item in sorted(combinations)],
        "parameter_count": route_runs[0].get("parameter_count") if route_runs else None,
        "epochs_run": {str(run["seed"]): run.get("epochs_run") for run in route_runs},
        "best_epoch": {str(run["seed"]): run.get("best_epoch") for run in route_runs},
        "training_seconds": mean_std([run.get("training_seconds") for run in route_runs]),
        "inference_seconds": mean_std([run.get("inference_seconds") for run in route_runs]),
        "peak_gpu_memory_bytes": max((run.get("peak_gpu_memory_bytes", 0) for run in route_runs), default=0),
        "per_case": per_case, "per_family": per_family, "per_background": per_background,
        "macro_position_rmse_over_dp": macro("learned_position_rmse_over_dp"),
        "macro_velocity_rmse_mps": macro("learned_velocity_rmse_mps"),
        "macro_com_rmse_m": macro("learned_com_rmse_m"),
    }


def conclusion(report: dict[str, Any]) -> str:
    route_rows = []
    for route, value in report["routes"].items():
        macro = value["macro_position_rmse_over_dp"]["bootstrap"]
        route_rows.append(f"| {route} | {value['run_count']} | {value['seeds']} | {macro['estimate'] if macro['estimate'] is not None else 'n/a'} | {macro['q025'] if macro['q025'] is not None else 'n/a'}–{macro['q975'] if macro['q975'] is not None else 'n/a'} |")
    return """# R3 G4 结论：因果输入与多路线学习基线

状态：**development-only；基线路线和指标闭环已执行，但当前 W11 pilot 没有完整边界三角形 sidecar，因此不能宣布正式学习排行榜或物理验收。**

## 路线与统一口径

| 路线 | runs | seeds | case-macro position RMSE/dp | case bootstrap 95% |
|---|---:|---|---:|---:|
""" + "\n".join(route_rows) + """

所有学习路线都使用初始质量加权 COM、统一的 solver velocity 状态（训练使用当前帧速度，rollout 从帧 0 速度开始并只消费自己的下一帧速度）、不依赖文件终点的 elapsed time，以及相同的 `8*tanh(raw/8)` 平滑输出上限。位置、速度和 COM 均采用向量范数 RMSE；bootstrap 的重采样单位是物理案例而不是帧。

常速度结果仅作为弱、确定性的参照。学习器相对常速度的退化率逐案例报告，但**不作为场景准入门槛**；困难且可信的案例仍应保留。

## 因果输入与已知限制

当前 pilot 的 F2 提供当前时刻的规定杯体控制曲线，F1/F3 没有 control group；未来流体状态、未来密度/压力和自由刚体未来轨迹没有进入 rollout。密度、压力、质量仅作为初始属性。所有 12 个可训练 fluid cases 的 boundary availability 仍为 false，因为 W11 尚未发布完整 wall triangle sidecar；这是真实阻塞项，不是由零向量伪造的几何输入。

本轮只评测 T1 numerical particle rollout。T2 material transport、T3 external observables 和 F6 coupled free-body route 不在该实验中打分。

## 学习曲线和下一步

每个 route/seed 最多 8 epochs，至少 3 epochs；以 validation autonomous rollout 的 case macro RMSE、patience=2 和 min-delta 作为停止与 checkpoint 选择规则，并在机器可读报告中保存每一 epoch 曲线。下一步应先补齐边界 sidecar，再复跑相同 matrix；之后才考虑三维 F6 的 coupled body-state model。

机器可读明细见 `r3-g4-baseline-audit.json`；实际运行入口和 GPU 分配见 `r3_g4_run_manifest.json`。
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--run-manifest", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--conclusion", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    run_manifest = json.loads(args.run_manifest.read_text())
    inventory = json.loads(args.inventory.read_text())
    lab_root = args.run_manifest.resolve().parents[1]
    runs, artifact_issues = load_runs(args.results_dir, run_manifest, lab_root)
    physical_runs = run_manifest.get("runs", [])
    combinations = [(run.get("route"), int(run.get("seed"))) for run in runs]
    expected = [(route, seed) for route in ROUTES for seed in SEEDS]
    gpu_audit = audit_gpu_manifest(run_manifest, config, inventory, expected)
    routes = {route: aggregate_route(route, runs) for route in ROUTES}
    all_case_entries = [entry for route in routes.values() for entry in route["per_case"].values()]
    report = {
        "schema_version": 1, "scope": "R3-G4 corrected development baseline audit",
        "execution_status": "complete" if len(runs) == len(expected) else "partial",
        "config": config,
        "run_manifest": {
            "path": str(args.run_manifest), "status": run_manifest.get("status"),
            "run_count": len(physical_runs), "physical_gpu_gate": gpu_audit["pass"],
            "physical_gpu_audit": gpu_audit,
            "artifact_provenance_gate": not artifact_issues,
            "artifact_provenance_issues": artifact_issues,
            "allowed_gpu_indices": sorted(int(value) for value in config.get("allowed_gpu_indices", [])),
            "runs": physical_runs,
        },
        "run_count": len(runs), "expected_run_count": len(expected),
        "route_seed_gate": sorted(combinations) == sorted(expected) and len(set(combinations)) == len(combinations),
        "routes": routes,
        "case_count_per_route": {route: len(value["per_case"]) for route, value in routes.items()},
        "boundary_geometry_gate": all(entry["boundary_available"] for entry in all_case_entries) if all_case_entries else False,
        "nonfinite_rollout_gate": all(all(status == "completed" for status in entry["status_by_seed"].values()) for entry in all_case_entries),
        "physics_budget": {
            "status": "diagnostic_only",
            "mass_identity_preservation_reported": True,
            "predicted_density_pressure": False,
            "material_transport_scored": False,
        },
        "degradation_policy": "diagnostic_per_case; never a physical-scene admission gate",
        "formal_ready": False,
        "open_blockers": [
            "W11 pilot has no complete boundary triangle sidecars; boundary availability gate is false",
            "only T1 particle rollout is scored; material transport and external observable tracks remain separate",
            "F6 free-body case has no fluid state in the pilot and is excluded until a coupled body-state route exists",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    args.conclusion.parent.mkdir(parents=True, exist_ok=True)
    args.conclusion.write_text(conclusion(report))
    print(json.dumps({"run_count": len(runs), "route_seed_gate": report["route_seed_gate"], "physical_gpu_gate": report["run_manifest"]["physical_gpu_gate"], "artifact_provenance_gate": report["run_manifest"]["artifact_provenance_gate"], "boundary_geometry_gate": report["boundary_geometry_gate"], "routes": {k: v["macro_position_rmse_over_dp"]["bootstrap"] for k, v in routes.items()}}, indent=2))


if __name__ == "__main__":
    main()
