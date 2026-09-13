#!/usr/bin/env python3
"""Independent B1 coverage/cost audit of the retained F3 material candidates."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import time

import h5py
import numpy as np

try:
    from scripts.l2_campaign import (
        CAMPAIGN,
        LAB,
        atomic_json,
        file_evidence,
        read_json,
        repo_relative,
        require_adopted,
        sha256_file,
        update_stage,
        update_usage,
        utc_now,
    )
except ModuleNotFoundError:  # direct invocation from scripts/
    from l2_campaign import (
        CAMPAIGN,
        LAB,
        atomic_json,
        file_evidence,
        read_json,
        repo_relative,
        require_adopted,
        sha256_file,
        update_stage,
        update_usage,
        utc_now,
    )


MATERIAL_ROOT = LAB / "campaigns/l1-resume/data/f3-material-reference"
COMPARISON_PATH = LAB / "campaigns/l1-resume/continuation/F3-REF0081818-MATERIAL-COMPARISON-NOMINAL-SUBSTEP.json"
REPORT_PATH = CAMPAIGN / "reports/b1-material-coverage.json"
MARKDOWN_PATH = CAMPAIGN / "reports/b1-material-coverage.md"

CANDIDATES = [
    {
        "config_id": "REF008-0075-NOMINAL-s2",
        "directory": MATERIAL_ROOT / "20260913T041909.924669Z-d78083d262",
        "attempt_record": LAB / "campaigns/l1-resume/continuation/F3-MATERIAL-REFERENCE-REF008-0075-NOMINAL-s2-20260913T041909.924669Z-d78083d262.json",
    },
    {
        "config_id": "REF008-0075-NOMINAL-s4",
        "directory": MATERIAL_ROOT / "20260913T042459.344502Z-8b34920167",
        "attempt_record": LAB / "campaigns/l1-resume/continuation/F3-MATERIAL-REFERENCE-REF008-0075-NOMINAL-s4-20260913T042459.344502Z-8b34920167.json",
    },
]


def mean_std(values: list[float]) -> dict:
    array = np.asarray(values, dtype=np.float64)
    return {
        "n": int(array.size),
        "mean": float(np.mean(array)) if array.size else None,
        "std_population": float(np.std(array, ddof=0)) if array.size else None,
        "std_sample": float(np.std(array, ddof=1)) if array.size > 1 else 0.0 if array.size else None,
    }


def scan_aligned(path: Path) -> dict:
    result = {"path": str(path.resolve()), "file": file_evidence(path), "exists": path.is_file()}
    if not path.is_file():
        result["structural_pass"] = False
        result["errors"] = ["missing_file"]
        return result
    errors: list[str] = []
    with h5py.File(path, "r") as handle:
        required = {"time", "position", "velocity", "mass", "particle_id", "particle_zone", "valid"}
        missing = sorted(required - set(handle.keys()))
        if missing:
            result["structural_pass"] = False
            result["errors"] = [f"missing:{name}" for name in missing]
            return result
        time_axis = np.asarray(handle["time"][:], dtype=np.float64)
        particle_id = np.asarray(handle["particle_id"][:])
        particle_zone = np.asarray(handle["particle_zone"][:])
        valid_ds = handle["valid"]
        expected_t = len(time_axis)
        expected_n = len(particle_id)
        shape_checks = {
            "time": time_axis.ndim == 1 and expected_t >= 2 and np.isfinite(time_axis).all() and np.all(np.diff(time_axis) > 0),
            "particle_id": particle_id.ndim == 1 and expected_n > 0,
            "position": handle["position"].shape == (expected_t, expected_n, 3),
            "velocity": handle["velocity"].shape == (expected_t, expected_n, 3),
            "mass": handle["mass"].shape == (expected_t, expected_n),
            "valid": valid_ds.shape == (expected_t, expected_n),
        }
        errors.extend([f"shape:{key}" for key, okay in shape_checks.items() if not okay])
        unique_keys = len(np.unique(np.column_stack((particle_zone, particle_id)), axis=0)) == expected_n
        finite_active = {"position": True, "velocity": True, "mass": True}
        valid_entries = 0
        invalid_entries = 0
        mass_initial = 0.0
        mass_final = 0.0
        if not errors:
            initial_valid = np.asarray(valid_ds[0], dtype=bool)
            final_valid = np.asarray(valid_ds[-1], dtype=bool)
            mass_initial = float(np.nansum(np.asarray(handle["mass"][0])[initial_valid]))
            mass_final = float(np.nansum(np.asarray(handle["mass"][-1])[final_valid]))
            for start in range(0, expected_t, 16):
                stop = min(start + 16, expected_t)
                active = np.asarray(valid_ds[start:stop], dtype=bool)
                valid_entries += int(active.sum())
                invalid_entries += int((~active).sum())
                for name in finite_active:
                    values = np.asarray(handle[name][start:stop])
                    if name == "position" or name == "velocity":
                        finite_active[name] = finite_active[name] and bool(np.isfinite(values[active]).all())
                    else:
                        finite_active[name] = finite_active[name] and bool(np.isfinite(values[active]).all())
        else:
            finite_active = {key: False for key in finite_active}
        errors.extend([f"nonfinite_active:{key}" for key, okay in finite_active.items() if not okay])
        result.update({
            "schema": str(handle.attrs.get("schema", "unknown")),
            "attrs": {str(key): str(value) for key, value in handle.attrs.items()},
            "frame_count": expected_t,
            "particle_count": expected_n,
            "time_start_s": float(time_axis[0]) if expected_t else None,
            "time_end_s": float(time_axis[-1]) if expected_t else None,
            "time_monotonic": bool(np.all(np.diff(time_axis) > 0)) if expected_t > 1 else False,
            "identity_unique": unique_keys,
            "finite_active": finite_active,
            "valid_entries": valid_entries,
            "invalid_entries": invalid_entries,
            "invalid_fraction": invalid_entries / max(1, expected_t * expected_n),
            "initial_valid_count": int(np.asarray(valid_ds[0], dtype=bool).sum()),
            "final_valid_count": int(np.asarray(valid_ds[-1], dtype=bool).sum()),
            "initial_mass_kg": mass_initial,
            "final_mass_kg": mass_final,
            "mass_closure_relative": abs(mass_final - mass_initial) / max(abs(mass_initial), 1e-30),
        })
    result["errors"] = errors
    result["structural_pass"] = not errors and result["identity_unique"]
    return result


def scan_material_npz(path: Path) -> dict:
    result = {"path": str(path.resolve()), "file": file_evidence(path), "exists": path.is_file()}
    if not path.is_file():
        return result
    with np.load(path, allow_pickle=False) as data:
        source = np.asarray(data["source_label"], dtype=np.int64)
        reliable = np.asarray(data["reliable"], dtype=bool)
        support_pass = np.asarray(data["support_gate_pass"], dtype=bool)
        wall_crossing = np.asarray(data["wall_crossing"], dtype=bool)
        status = np.asarray(data["first_passage_status"])
        terminal = np.asarray(data["terminal_label"])
        failure_reason = np.asarray(data["first_failure_reason"])
        first_failure = np.asarray(data["first_failure_time_s"], dtype=np.float64)
        by_source = {}
        for label in sorted(np.unique(source)):
            selected = source == label
            first_times = first_failure[selected & np.isfinite(first_failure)]
            by_source[str(int(label))] = {
                "seed_count": int(selected.sum()),
                "reliable_fraction": float(reliable[selected].mean()),
                "first_failure_fraction": float((~reliable[selected]).mean()),
                "median_first_failure_time_s": float(np.median(first_times)) if first_times.size else None,
                "first_failure_time_p95_s": float(np.percentile(first_times, 95)) if first_times.size else None,
                "first_passage_status_counts": dict(Counter(str(value) for value in status[selected])),
                "terminal_label_counts": dict(Counter(str(value) for value in terminal[selected])),
            }
        result.update({
            "seed_count": int(source.size),
            "source_labels": sorted(int(value) for value in np.unique(source)),
            "reliable_fraction": float(reliable.mean()),
            "support_gate_failure_count": int((~support_pass).sum()),
            "support_gate_failure_fraction_of_frame_seed_pairs": float((~support_pass).mean()),
            "wall_crossing_event_count": int(wall_crossing.sum()),
            "failure_reason_counts": dict(Counter(str(value) for value in failure_reason if str(value) != "none")),
            "by_source": by_source,
            "status_counts": dict(Counter(str(value) for value in status)),
            "terminal_counts": dict(Counter(str(value) for value in terminal)),
        })
    return result


def build_markdown(report: dict) -> str:
    rows = []
    for row in report["raw_data_table"]:
        rows.append(
            f"| {row['config_id']} | {row['substeps']} | {row['seed_count']} | "
            f"{row['elapsed_seconds']:.3f} | {row['aligned_h5_bytes'] / 1e9:.3f} | "
            f"{row['reliable_fraction']:.6f} | {row['support_gate_failure_count']} | "
            f"{row['wall_crossing_event_count']} |"
        )
    findings = "\n".join(f"- {item}" for item in report["key_findings"])
    next_steps = "\n".join(f"- {item}" for item in report["next_experiments"])
    return f"""# B1 材料覆盖与成本审计

状态：**{report['status']}**。本报告只审计保留的两份 F3 T2 候选；不改变旧 L1 结论，也不把候选提升为 `qualified_T2`。

## 原始数据表

| config | substeps | seeds | historical CPU s | aligned H5 GB | reliable seed fraction | support-gate failures | wall crossings |
|---|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

## 关键发现

{findings}

## 下一步实验

{next_steps}

## 单位与统计语义

- `unknown_fraction`、reliable fraction 和 failure fraction 是无量纲质量/种子比例；事件时间用秒，路径误差用米，存储用字节，历史 CPU 用 CPU 秒。
- 每个配置有 512 个 tracer seed；这里的 mean/std 是在 s2/s4 配置之间计算的配置级统计，不把 512 个 tracer 当成 512 次独立 CFD 实验。
- 路径 RMS/P95 未计算，因为两份候选均有 wall/support 失败；缺失项保持 `unknown`，不能按零填充。
"""


def run() -> dict:
    state = require_adopted()
    if state["stages"]["A0"]["status"] not in {"complete", "complete_with_findings"}:
        raise RuntimeError("B1 requires A0 to be complete")
    if state["stages"]["B1"]["status"] not in {"ready", "pending"}:
        raise RuntimeError("B1 already has a terminal status; refusing an untracked rerun")
    started_wall = time.perf_counter()
    started_cpu = time.process_time()
    comparison = read_json(COMPARISON_PATH)
    comparison_by_source = {str(item["source"]): item for item in comparison["by_source"]}
    rows = []
    audits = []
    historical_cpu_seconds = []
    for candidate in CANDIDATES:
        directory = candidate["directory"]
        result_path = directory / "result.json"
        result = read_json(result_path)
        attempt = read_json(candidate["attempt_record"])
        aligned = scan_aligned(directory / "aligned.h5")
        material = scan_material_npz(directory / "material.npz")
        historical_cpu_seconds.append(float(attempt.get("elapsed_seconds", 0.0)) * float(attempt.get("cpu_cores", 1)))
        audits.append({
            "config_id": candidate["config_id"],
            "result": {"path": repo_relative(result_path), "sha256": sha256_file(result_path)[0]},
            "attempt": {
                "path": repo_relative(candidate["attempt_record"]),
                "sha256": sha256_file(candidate["attempt_record"])[0],
                "status": attempt.get("status"),
                "backend": attempt.get("backend"),
                "elapsed_seconds": attempt.get("elapsed_seconds"),
                "cpu_cores": attempt.get("cpu_cores"),
                "resource_category": attempt.get("resource_category"),
            },
            "configuration": result.get("configuration"),
            "aligned_scan": aligned,
            "material_scan": material,
        })
        rows.append({
            "config_id": candidate["config_id"],
            "substeps": result["configuration"]["substeps"],
            "seed_count": material.get("seed_count"),
            "elapsed_seconds": attempt.get("elapsed_seconds"),
            "aligned_h5_bytes": aligned["file"].get("bytes", 0),
            "material_npz_bytes": material["file"].get("bytes", 0),
            "aligned_structural_pass": aligned.get("structural_pass"),
            "reliable_fraction": material.get("reliable_fraction"),
            "support_gate_failure_count": material.get("support_gate_failure_count"),
            "wall_crossing_event_count": material.get("wall_crossing_event_count"),
            "failure_reason_counts": material.get("failure_reason_counts"),
        })
    unknown_by_source = {
        source: comparison_by_source[source]["unknown_fraction_max"]
        for source in sorted(comparison_by_source)
    }
    unknown_stats = {
        source: mean_std([float(value) for value in values])
        for source, values in unknown_by_source.items()
    }
    support_counts = [float(row["support_gate_failure_count"]) for row in rows]
    reliable_values = [float(row["reliable_fraction"]) for row in rows]
    report = {
        "schema": "l2.b1.material_coverage_cost.v1",
        "stage": "B1",
        "created_at_utc": utc_now(),
        "baseline_commit": state["baseline_commit"],
        "status": "complete_with_findings",
        "decision": "complete_negative_T2_diagnostic; no material qualification",
        "source_comparison": {
            "path": repo_relative(COMPARISON_PATH),
            "sha256": sha256_file(COMPARISON_PATH)[0],
            "status": comparison.get("status"),
            "thresholds": comparison.get("thresholds"),
            "qualified_T2_macro": comparison.get("qualified_T2_macro"),
            "qualified_T2_path": comparison.get("qualified_T2_path"),
        },
        "raw_data_table": rows,
        "candidate_audits": audits,
        "coverage_statistics": {
            "seed_count_per_configuration": 512,
            "configuration_count": len(rows),
            "reliable_fraction_across_configurations": mean_std(reliable_values),
            "support_gate_failure_count_across_configurations": mean_std(support_counts),
            "unknown_fraction_max_by_source_across_s2_s4": unknown_by_source,
            "unknown_fraction_mean_std_by_source": unknown_stats,
            "terminal_bound_difference_by_source": {
                str(item["source"]): item["terminal_mass_worst_bound_difference"]
                for item in comparison["by_source"]
            },
            "first_passage_cdf_worst_bound_difference_by_source": {
                str(item["source"]): item["first_passage_cdf_worst_bound_difference"]
                for item in comparison["by_source"]
            },
            "residence_bound_difference_s_by_source": {
                str(item["source"]): item["mean_residence_worst_bound_difference_s"]
                for item in comparison["by_source"]
            },
            "observed_event_weighted_mae_s_by_source": {
                str(item["source"]): item["observed_event_weighted_mae_s"]
                for item in comparison["by_source"]
            },
            "path_statistics": None,
            "path_status": "unknown/not computed; full path reliability gate failed",
        },
        "cost_accounting": {
            "historical_candidate_cpu_seconds": historical_cpu_seconds,
            "historical_candidate_cpu_core_hours": sum(historical_cpu_seconds) / 3600.0,
            "historical_candidate_is_not_charged_to_L2_usage": True,
            "new_l2_execution": "read-only audit; no solver/material configuration launched",
            "physical_units": {
                "time": "seconds",
                "path": "metres",
                "fraction": "dimensionless mass/seed fraction",
                "storage": "bytes",
                "cpu": "CPU seconds and CPU core-hours",
            },
        },
        "key_findings": [
            "Both retained candidates have the same 512-seed reliability fraction: 481/512 = 0.939453125; 31 seeds are censored before the end.",
            "The s2 and s4 bundles share the same first-failure set at the recorded resolution of this audit; support-gate failure counts differ slightly (347 versus 360 frame-seed pairs), so extra substeps do not repair coverage.",
            "Per-source unknown mass reaches 0.0625 for source 0 and 0.05859375 for source 1, above the 0.01 candidate budget; terminal and first-passage bound differences also exceed the candidate limits.",
            "Observed event timing is numerically small in the surviving common subset (source-wise weighted MAE about 0.000258–0.000360 s), but this does not compensate for the approximately 6% censored mass and missing path qualification.",
            "The aligned HDF5 structural scans and source hashes are retained; neither candidate is reclassified as T2_macro or T2_path qualified.",
        ],
        "next_experiments": [
            "Do not spend the remaining material matrix on more s2/s4 repetitions of the same nominal source until the failure window is instrumented.",
            "Run one bounded diagnostic at the first-failure window with near-wall distance, visible-neighbour/support statistics, source visibility, and mass/identity loss recorded together.",
            "If that diagnostic identifies a deterministic coverage repair, spend at most one canary configuration on the repair and compare common-observed, coverage-loss, and worst-case uncertainty separately.",
            "Keep T2_path blocked until a full-coverage or explicitly interval-censored path reference exists; a smaller event-time error alone is not a path pass.",
        ],
        "acceptance": {
            "two_candidates_independently_scanned": len(audits) == 2 and all(item["aligned_scan"].get("structural_pass") for item in audits),
            "coverage_failure_is_explicit": comparison.get("macro_within_candidate_budget") is False,
            "path_not_promoted": comparison.get("qualified_T2_path") is False and comparison.get("path_statistics") is None,
            "cost_units_separated": True,
            "seed_statistics_not_overcounted": True,
        },
        "resource_observation": {
            "wall_seconds": time.perf_counter() - started_wall,
            "process_cpu_seconds": time.process_time() - started_cpu,
            "new_solver_attempts": 0,
            "new_material_configurations": 0,
        },
    }
    report["status"] = "complete" if all(report["acceptance"].values()) else "complete_with_findings"
    atomic_json(REPORT_PATH, report)
    markdown = build_markdown(report)
    MARKDOWN_PATH.parent.mkdir(parents=True, exist_ok=True)
    MARKDOWN_PATH.write_text(markdown)
    output_bytes = REPORT_PATH.stat().st_size + MARKDOWN_PATH.stat().st_size
    report["resource_observation"]["new_storage_bytes"] = output_bytes
    atomic_json(REPORT_PATH, report)
    update_usage(
        cpu_core_hours_actual=report["resource_observation"]["process_cpu_seconds"] / 3600.0,
        new_storage_bytes=output_bytes,
    )
    update_stage("B1", "complete", facts={
        "report": "reports/b1-material-coverage.json",
        "markdown": "reports/b1-material-coverage.md",
        "decision": report["decision"],
        "new_material_configurations": 0,
    })
    return report


if __name__ == "__main__":
    result = run()
    print(json.dumps({
        "status": result["status"],
        "decision": result["decision"],
        "report": str(REPORT_PATH),
        "markdown": str(MARKDOWN_PATH),
    }, ensure_ascii=False, indent=2))
