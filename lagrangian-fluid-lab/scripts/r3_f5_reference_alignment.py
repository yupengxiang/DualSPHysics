#!/usr/bin/env python3
"""Candidate-only alignment probe for the official CIEMito WaveRunup table.

The bundled external table is an Eulerian wave-gauge/run-up reference.  This
module compares only the four wave-gauge columns with the external SWL lines
emitted by :mod:`r3_f5_wave_runup`; it never turns the table into particle
truth or authorizes a formal validation release.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np

# Make direct ``python lagrangian-fluid-lab/scripts/...`` invocation behave
# like the documented ``cd lagrangian-fluid-lab && python scripts/...`` form.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.r3_f45_external_feasibility import inspect_wave_gauge_layout
from scripts.r3_f5_wave_runup import EXTERNAL_GAUGES, _load_gauge


LAB = Path(__file__).resolve().parents[1]
OFFICIAL = LAB / "vendor" / "official" / "DualSPHysics_v5.4"
SOURCE = OFFICIAL / "examples" / "main" / "17_WaveRunup"
DEFAULT_RUN_REPORT = LAB / "campaigns" / "v0.1-candidate" / "r3-f5-wave-runup.json"
DEFAULT_OUTPUT = LAB / "campaigns" / "v0.1-candidate" / "r3-f5-reference-alignment.json"
DEFAULT_CONCLUSION = LAB / "campaigns" / "v0.1-candidate" / "R3-F5-REFERENCE-ALIGNMENT.md"


def sha256(path: Path) -> str | None:
    if not Path(path).is_file():
        return None
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_reference(path: Path) -> dict[str, Any]:
    """Load the six-column table and aggregate only duplicate timestamps.

    The original row count and duplicate-time values remain in the returned
    metadata.  Aggregation is used solely so ``numpy.interp`` has a strictly
    increasing time axis.
    """

    lines = Path(path).read_text(errors="replace").splitlines()
    header_line = next((line.strip() for line in lines if line.strip()), "")
    rows: list[list[float]] = []
    for raw in lines[1:]:
        try:
            values = [float(value) for value in raw.split()]
        except ValueError:
            continue
        if len(values) == 6 and np.all(np.isfinite(values)):
            rows.append(values)
    original = np.asarray(rows, dtype=np.float64)
    if original.ndim != 2 or original.shape != (len(rows), 6) or len(original) < 2:
        raise ValueError("reference table must contain at least two finite six-column rows")
    if not np.all(np.diff(original[:, 0]) >= 0.0):
        raise ValueError("reference timestamps must be non-decreasing")
    times, inverse = np.unique(original[:, 0], return_inverse=True)
    aggregate = np.zeros((len(times), 6), dtype=np.float64)
    aggregate[:, 0] = times
    for index in range(len(times)):
        aggregate[index, 1:] = original[inverse == index, 1:].mean(axis=0)
    duplicate_mask = np.diff(original[:, 0]) == 0.0
    return {
        "path": str(path),
        "sha256": sha256(path),
        "header": header_line.split(),
        "original_rows": int(len(original)),
        "unique_time_rows": int(len(aggregate)),
        "duplicate_transition_count": int(np.count_nonzero(duplicate_mask)),
        "duplicate_time_values_s": np.unique(original[:-1, 0][duplicate_mask]).tolist(),
        "time_start_s": float(original[0, 0]),
        "time_end_s": float(original[-1, 0]),
        "data": aggregate,
    }


def compare_series(model: np.ndarray, reference: np.ndarray, *, offset_s: float) -> dict[str, Any]:
    """Compare model ``swlz`` perturbation against one reference gauge."""

    if model.ndim != 2 or model.shape[1] < 4 or len(model) < 2:
        return {"status": "insufficient_model_rows"}
    model_time = model[:, 0]
    model_eta = model[:, 3] - model[0, 3]
    ref_time = reference[:, 0]
    lo = max(float(model_time[0]), float(ref_time[0] - offset_s))
    hi = min(float(model_time[-1]), float(ref_time[-1] - offset_s))
    if hi <= lo:
        return {"status": "no_overlap", "offset_s": offset_s}
    mask = (model_time >= lo) & (model_time <= hi)
    if np.count_nonzero(mask) < 2:
        return {"status": "insufficient_overlap", "offset_s": offset_s}
    t = model_time[mask]
    external = np.interp(t + offset_s, ref_time, reference[:, 1])
    residual = model_eta[mask] - external
    return {
        "status": "computed",
        "offset_s": float(offset_s),
        "overlap_start_s": float(t[0]),
        "overlap_end_s": float(t[-1]),
        "samples": int(len(t)),
        "rmse_m": float(np.sqrt(np.mean(residual ** 2))),
        "mae_m": float(np.mean(np.abs(residual))),
        "max_abs_m": float(np.max(np.abs(residual))),
    }


def _compare_at_offset(model: np.ndarray, reference: np.ndarray, ref_column: int, offset_s: float) -> dict[str, Any]:
    if model.ndim != 2 or model.shape[1] < 4 or len(model) < 2:
        return {"status": "insufficient_model_rows"}
    model_time = model[:, 0]
    model_eta = model[:, 3] - model[0, 3]
    ref_time = reference[:, 0]
    lo = max(float(model_time[0]), float(ref_time[0] - offset_s))
    hi = min(float(model_time[-1]), float(ref_time[-1] - offset_s))
    mask = (model_time >= lo) & (model_time <= hi)
    if hi <= lo or np.count_nonzero(mask) < 2:
        return {"status": "insufficient_overlap", "offset_s": float(offset_s)}
    t = model_time[mask]
    external = np.interp(t + offset_s, ref_time, reference[:, ref_column])
    residual = model_eta[mask] - external
    return {"status": "computed", "offset_s": float(offset_s), "rmse_m": float(np.sqrt(np.mean(residual ** 2)))}


def _score_at_offset(models: list[np.ndarray], reference: np.ndarray, offset_s: float) -> float | None:
    values = [_compare_at_offset(model, reference, index + 1, offset_s) for index, model in enumerate(models)]
    if any(item.get("status") != "computed" for item in values):
        return None
    return float(np.mean([item["rmse_m"] for item in values]))


def align_run(run: dict[str, Any], reference: dict[str, Any], *, min_overlap_s: float = 8.0) -> dict[str, Any]:
    ref = np.asarray(reference["data"], dtype=np.float64)
    model_series: dict[str, np.ndarray] = {}
    for gauge_name, *_ in EXTERNAL_GAUGES:
        path = Path(run["external_gauge_summary"]["gauges"][gauge_name]["path"])
        model_series[gauge_name] = _load_gauge(path)

    fixed: dict[str, Any] = {}
    fixed_rmse: list[float] = []
    for index, (gauge_name, model) in enumerate(model_series.items()):
        result = _compare_at_offset(model, ref, index + 1, 0.0)
        if result.get("status") == "computed":
            # Recompute the full fixed-zero metrics (rather than only RMSE).
            result = compare_series(model, ref[:, [0, index + 1]], offset_s=0.0)
            fixed_rmse.append(float(result["rmse_m"]))
        fixed[gauge_name] = result

    models = [model_series[name] for name, *_ in EXTERNAL_GAUGES]
    offsets = np.arange(-0.5, 0.5001, 0.002)
    candidates: list[tuple[float, float]] = []
    for offset in offsets:
        overlap = max(
            max(float(model[0, 0]), float(ref[0, 0] - offset)) if len(model) else 0.0
            for model in models
        )
        end = min(
            min(float(model[-1, 0]), float(ref[-1, 0] - offset)) if len(model) else 0.0
            for model in models
        )
        if end - overlap < min_overlap_s:
            continue
        score = _score_at_offset(models, ref, float(offset))
        if score is not None:
            candidates.append((score, float(offset)))
    candidates.sort()
    best = candidates[0] if candidates else None
    return {
        "label": run["label"],
        "dp_m": run.get("dp_m"),
        "run_status": run.get("status"),
        "run_output_dir": run.get("output_dir"),
        "fixed_zero_offset": {
            "meaning": "model t=0 aligned to reference t=0; model SWL baseline removed",
            "gauges": fixed,
            "mean_rmse_m": float(np.mean(fixed_rmse)) if fixed_rmse else None,
        },
        "local_shift_diagnostic": {
            "search_range_s": [-0.5, 0.5],
            "step_s": 0.002,
            "minimum_overlap_s": min_overlap_s,
            "best_mean_rmse_m": best[0] if best else None,
            "best_offset_s": best[1] if best else None,
            "interpretation": "diagnostic phase sensitivity only; not a fitted physical calibration",
        },
    }


def build_report(run_report: dict[str, Any], reference: dict[str, Any]) -> dict[str, Any]:
    runs = [run for run in run_report.get("runs", []) if run.get("status") == "completed"]
    return {
        "schema_version": 1,
        "scope": "R3 F5 candidate external CIEMito alignment probe",
        "status": "candidate_only",
        "formal_release_authorized": False,
        "reference": {
            key: value for key, value in reference.items() if key != "data"
        },
        "external_gauge_layout": inspect_wave_gauge_layout(SOURCE / "wg1234.txt"),
        "model_contract": {
            "track": "Eulerian SWL gauge versus Eulerian external wave gauge",
            "particle_lineage_used": False,
            "baseline": "subtract each model gauge's first SWL sample",
            "duplicate_reference_times": "aggregate equal rounded timestamps by arithmetic mean for interpolation; retain original counts",
        },
        "runs": [align_run(run, reference) for run in runs],
        "limitations": [
            "The table does not provide particle-corresponded truth or a measurement uncertainty envelope.",
            "Reference/model coordinate and vertical datum equivalence are assumed only for this diagnostic and remain unverified.",
            "Local shift search is not a physical calibration and cannot turn a candidate run into a Gold label.",
            "Formal admission still requires pre-registered time alignment, uncertainty, event metrics, and independent review.",
        ],
    }


def render_conclusion(report: dict[str, Any]) -> str:
    lines = []
    for run in report.get("runs", []):
        fixed = run["fixed_zero_offset"].get("mean_rmse_m")
        best = run["local_shift_diagnostic"].get("best_mean_rmse_m")
        shift = run["local_shift_diagnostic"].get("best_offset_s")
        lines.append(
            f"- {run['label']} (dp={run['dp_m']} m): fixed t=0 mean RMSE "
            f"{fixed * 1000:.2f} mm; local ±0.5 s diagnostic "
            f"{best * 1000:.2f} mm at offset {shift:+.3f} s."
            if fixed is not None and best is not None and shift is not None
            else f"- {run['label']}: insufficient overlap for alignment metrics."
        )
    return """# R3 F5 CIEMito 外部波高计对齐探针

状态：**candidate-only；不授权正式数据发布**。

该探针将模型四条垂向 SWL 线与官方 CIEMito 表中的四列波高计观测进行对齐诊断。模型每条曲线先减去自身首个 SWL 值；参考表的原始重复时间戳被保留并按相同时间的算术平均用于插值。

结果仅回答“当前输出链能否形成可复查的时间序列比较”，不回答“数值模型已经通过外部物理验证”。

""" + "\n".join(lines) + """

仍未验证坐标/高程基准等价性、测量不确定度和预注册的事件指标；局部时移只是相位敏感性诊断，不能作为物理校准。机器可读详情见 `r3-f5-reference-alignment.json`。
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-report", type=Path, default=DEFAULT_RUN_REPORT)
    parser.add_argument("--reference", type=Path, default=SOURCE / "EXP_CaseWaveRunup_CIEMito.txt")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--conclusion", type=Path, default=DEFAULT_CONCLUSION)
    args = parser.parse_args()
    run_report = json.loads(args.run_report.read_text())
    reference = load_reference(args.reference)
    report = build_report(run_report, reference)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    args.conclusion.parent.mkdir(parents=True, exist_ok=True)
    args.conclusion.write_text(render_conclusion(report))
    print(json.dumps({
        "status": report["status"],
        "formal_release_authorized": report["formal_release_authorized"],
        "reference_original_rows": reference["original_rows"],
        "reference_duplicate_transition_count": reference["duplicate_transition_count"],
        "runs": len(report["runs"]),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
