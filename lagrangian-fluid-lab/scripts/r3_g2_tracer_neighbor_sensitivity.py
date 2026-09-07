#!/usr/bin/env python3
"""Probe wall-aware tracer sensitivity to neighbours, regularization and steps.

This is a deliberately small, one-factor-at-a-time numerical probe.  It uses
the independent Shepard/Heun tracer from :mod:`passive_tracers`, the exact
same-solver particle identities as the existing G2 convergence audit, and the
finite world-space boundary sidecars.  The result is useful for finding an
unstable tracer configuration; it is *not* a physical validation or a release
acceptance test.

The default sweep contains one baseline and five perturbations per case:

* neighbours: 12, 24, 48 (baseline 24);
* regularization: 0.05, 0.10, 0.20 times ``dp`` (baseline 0.10 ``dp``);
* integration substeps: 1 and 4 per saved solver interval (baseline 4).

Only one factor changes in each perturbation.  This keeps the small CPU matrix
interpretable while still exposing all three knobs.  ``--full-factorial`` is
available when a later campaign needs interactions between the factors.
Every run requires an audited sidecar and remains ``candidate-only`` because
sidecar face policy, destination regions, and external physical validation are
outside this probe.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time as wall_time
from typing import Any, Iterable

import h5py
import numpy as np

try:
    from scripts.boundary_sidecars import audit_sidecar, sidecar_provider
    from scripts.passive_tracers import advect_hdf5, weighted_stratified_seeds
    from scripts.r3_g2_tracer_convergence import (
        DEFAULT_CASES,
        DEFAULT_MANIFEST,
        LAB,
        _load_cases,
        _solver_reference,
        _trajectory_summary,
        compare_traces,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from boundary_sidecars import audit_sidecar, sidecar_provider
    from passive_tracers import advect_hdf5, weighted_stratified_seeds
    from r3_g2_tracer_convergence import (
        DEFAULT_CASES,
        DEFAULT_MANIFEST,
        LAB,
        _load_cases,
        _solver_reference,
        _trajectory_summary,
        compare_traces,
    )


CAMPAIGN = LAB / "campaigns" / "v0.1-candidate"
DEFAULT_SIDECAR_DIR = CAMPAIGN / "sidecars" / "r3-g2-boundary"
DEFAULT_REPORT = CAMPAIGN / "r3-g2-tracer-neighbour-sensitivity.json"
DEFAULT_CONCLUSION = CAMPAIGN / "R3-G2-TRACER-NEIGHBOUR-SENSITIVITY.md"
DEFAULT_COUNT = 16
DEFAULT_FRAME_STRIDE = 1
DEFAULT_MAX_SUPPORT_OVER_DP = 1.75
DEFAULT_BASELINE = {
    "label": "baseline",
    "neighbours": 24,
    "regularization_over_dp": 0.1,
    "substeps_per_interval": 4,
    "varied_parameter": "none",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _positive_ints(values: Iterable[int], name: str) -> tuple[int, ...]:
    result = tuple(int(value) for value in values)
    if not result or any(value < 1 for value in result):
        raise ValueError(f"{name} must contain positive integers")
    return result


def _positive_floats(values: Iterable[float], name: str) -> tuple[float, ...]:
    result = tuple(float(value) for value in values)
    if not result or any(not np.isfinite(value) or value <= 0 for value in result):
        raise ValueError(f"{name} must contain finite positive values")
    return result


def _setting(label: str, neighbours: int, regularization_over_dp: float,
             substeps_per_interval: int, varied_parameter: str) -> dict[str, Any]:
    neighbours = int(neighbours)
    substeps_per_interval = int(substeps_per_interval)
    regularization_over_dp = float(regularization_over_dp)
    if neighbours < 1:
        raise ValueError("neighbours must be positive")
    if substeps_per_interval < 1:
        raise ValueError("substeps_per_interval must be positive")
    if not np.isfinite(regularization_over_dp) or regularization_over_dp <= 0:
        raise ValueError("regularization_over_dp must be finite and positive")
    return {
        "label": str(label),
        "neighbours": neighbours,
        "regularization_over_dp": regularization_over_dp,
        "substeps_per_interval": substeps_per_interval,
        "varied_parameter": str(varied_parameter),
    }


def build_settings(neighbours: Iterable[int] = (12, 24, 48),
                   regularization_over_dp: Iterable[float] = (0.05, 0.1, 0.2),
                   substeps: Iterable[int] = (1, 4), *,
                   full_factorial: bool = False) -> list[dict[str, Any]]:
    """Build a deterministic parameter list with a protected baseline.

    The default is one-factor-at-a-time: values different from the baseline in
    each axis are retained, but the other two axes stay at the baseline.  This
    produces six settings
    and prevents a small CPU probe from being mistaken for a complete design of
    experiments.  ``full_factorial`` explicitly opts into the Cartesian product.
    """
    neighbours = _positive_ints(neighbours, "neighbours")
    regularization_over_dp = _positive_floats(regularization_over_dp, "regularization_over_dp")
    substeps = _positive_ints(substeps, "substeps")
    baseline = dict(DEFAULT_BASELINE)
    settings: list[dict[str, Any]] = []

    parameter_keys: set[tuple[int, float, int]] = set()

    def append(label: str, k: int, reg: float, steps: int, varied: str) -> None:
        candidate = _setting(label, k, reg, steps, varied)
        key = (candidate["neighbours"], candidate["regularization_over_dp"],
               candidate["substeps_per_interval"])
        if key not in parameter_keys:
            parameter_keys.add(key)
            settings.append(candidate)

    append(baseline["label"], baseline["neighbours"], baseline["regularization_over_dp"],
           baseline["substeps_per_interval"], baseline["varied_parameter"])
    if full_factorial:
        settings = []
        parameter_keys.clear()
        for k in neighbours:
            for reg in regularization_over_dp:
                for steps in substeps:
                    baseline_parameters = (
                        k == baseline["neighbours"]
                        and reg == baseline["regularization_over_dp"]
                        and steps == baseline["substeps_per_interval"]
                    )
                    label = "baseline" if baseline_parameters else f"k{k}_reg{reg:g}_steps{steps}"
                    append(label, k, reg, steps,
                           "none" if baseline_parameters else "full_factorial")
        if not any(item["label"] == "baseline" for item in settings):
            # A caller may intentionally pass axes without the baseline.  Keep
            # the comparison well-defined by inserting it first.
            settings.insert(0, _setting(
                "baseline", baseline["neighbours"], baseline["regularization_over_dp"],
                baseline["substeps_per_interval"], "none"))
        return settings

    for k in neighbours:
        if k == baseline["neighbours"]:
            continue
        append(f"neighbours_{k}", k, baseline["regularization_over_dp"],
               baseline["substeps_per_interval"], "neighbours")
    for reg in regularization_over_dp:
        if reg == baseline["regularization_over_dp"]:
            continue
        append(f"regularization_{reg:g}dp", baseline["neighbours"], reg,
               baseline["substeps_per_interval"], "regularization_over_dp")
    for steps in substeps:
        if steps == baseline["substeps_per_interval"]:
            continue
        append(f"substeps_{steps}", baseline["neighbours"],
               baseline["regularization_over_dp"], steps, "substeps_per_interval")
    return settings


def _attr_text(value: Any) -> str | None:
    if isinstance(value, bytes):
        return value.decode()
    return str(value) if value is not None else None


def validate_sidecar_against_solver(sidecar_path: Path, solver_path: Path,
                                    case_id: str) -> dict[str, Any]:
    """Audit sidecar structure and ensure its frame axis matches the solver."""
    sidecar_path = Path(sidecar_path).resolve()
    solver_path = Path(solver_path).resolve()
    audit = audit_sidecar(sidecar_path)
    if audit["case_id"] != case_id:
        raise ValueError(
            f"{case_id}: sidecar case_id={audit['case_id']!r} does not match"
        )
    if audit["schema_version"] != "boundary-sidecar-v1":
        raise ValueError(f"{case_id}: unsupported sidecar schema {audit['schema_version']!r}")
    if audit["coordinate_frame"] != "world":
        raise ValueError(f"{case_id}: sidecar coordinate frame is not world")
    with h5py.File(sidecar_path, "r") as sidecar, h5py.File(solver_path, "r") as solver:
        sidecar_time = np.asarray(sidecar["time"][:], dtype=np.float64)
        solver_time = np.asarray(solver["time"][:], dtype=np.float64)
    if sidecar_time.shape != solver_time.shape or not np.allclose(
            sidecar_time, solver_time, atol=1e-10, rtol=0):
        raise ValueError(f"{case_id}: sidecar and solver time axes differ")
    audit["time_matches_solver"] = True
    audit["case_id"] = _attr_text(audit["case_id"])
    audit["schema_version"] = _attr_text(audit["schema_version"])
    audit["coordinate_frame"] = _attr_text(audit["coordinate_frame"])
    return audit


def _sidecar_path(manifest_path: Path, record: dict[str, Any], sidecar_dir: Path | None) -> Path:
    relative = (record.get("geometry") or {}).get("boundary_sidecar")
    if not isinstance(relative, str):
        raise ValueError(f"{record['case_id']}: release record has no boundary_sidecar")
    release_root = Path(manifest_path).resolve().parent
    linked = (release_root / relative).resolve()
    try:
        linked.relative_to(release_root)
    except ValueError as error:
        raise ValueError(f"{record['case_id']}: release boundary_sidecar escapes release root") from error
    if not linked.is_file():
        raise FileNotFoundError(linked)
    if sidecar_dir is None:
        return linked
    candidate = Path(sidecar_dir).resolve() / f"{record['case_id']}.h5"
    if not candidate.is_file():
        return candidate
    # A caller may use a staged/campaign copy for I/O, but it must be byte
    # identical to the release-linked artifact.  This prevents an arbitrary
    # same-shaped sidecar from bypassing the release contract.
    if _sha256(candidate) != _sha256(linked):
        raise ValueError(
            f"{record['case_id']}: sidecar copy differs from release-linked artifact"
        )
    return candidate


def run_case(case: dict[str, Any], h5_path: Path, sidecar_path: Path, *,
             settings: Iterable[dict[str, Any]], seed_count: int = DEFAULT_COUNT,
             frame_stride: int = DEFAULT_FRAME_STRIDE,
             maximum_support_over_dp: float = DEFAULT_MAX_SUPPORT_OVER_DP) -> dict[str, Any]:
    """Run one case over the sensitivity settings and compare to baseline."""
    if int(seed_count) < 1:
        raise ValueError("seed_count must be positive")
    if int(frame_stride) < 1:
        raise ValueError("frame_stride must be positive")
    if not np.isfinite(float(maximum_support_over_dp)) or maximum_support_over_dp <= 0:
        raise ValueError("maximum_support_over_dp must be finite and positive")
    settings = [dict(item) for item in settings]
    labels = [item.get("label") for item in settings]
    if len(set(labels)) != len(labels):
        raise ValueError("sensitivity setting labels must be unique")
    baseline_label = "baseline"
    if baseline_label not in labels:
        raise ValueError("sensitivity settings must include the baseline")

    h5_path = Path(h5_path).resolve()
    sidecar_path = Path(sidecar_path).resolve()
    sidecar_audit = validate_sidecar_against_solver(sidecar_path, h5_path, case["case_id"])
    barrier = sidecar_provider(sidecar_path)
    dp = float(case["numerics"]["particle_spacing_m"])
    with h5py.File(h5_path, "r") as h5:
        initial_fluid_mass = float(np.sum(
            h5["mass"][0][h5["valid"][0] & (h5["type"][0] == 3)]
        ))
    seeds = weighted_stratified_seeds(h5_path, maximum=int(seed_count))
    seeds["initial_fluid_mass"] = initial_fluid_mass
    traces: dict[str, dict[str, Any]] = {}
    solver_valid_by_label: dict[str, np.ndarray] = {}
    records: list[dict[str, Any]] = []
    for setting in settings:
        started = wall_time.perf_counter()
        trace = advect_hdf5(
            h5_path,
            seeds["position"],
            neighbours=int(setting["neighbours"]),
            regularization=float(setting["regularization_over_dp"]) * dp,
            maximum_support_distance=float(maximum_support_over_dp) * dp,
            frame_stride=int(frame_stride),
            substeps_per_interval=int(setting["substeps_per_interval"]),
            barrier_provider=barrier,
        )
        elapsed = wall_time.perf_counter() - started
        reference_time, reference_position, reference_valid = _solver_reference(
            h5_path, seeds["indices"], int(frame_stride)
        )
        if not np.allclose(reference_time, trace["time"], atol=1e-10, rtol=0):
            raise ValueError(f"{case['case_id']}: tracer time axis differs from solver")
        traces[str(setting["label"])] = trace
        solver_valid_by_label[str(setting["label"])] = reference_valid
        records.append({
            "configuration": setting,
            "summary": _trajectory_summary(
                trace, reference_position, reference_valid, seeds, dp, elapsed,
                boundary_available=True,
            ),
        })

    baseline = traces[baseline_label]
    for record in records:
        label = str(record["configuration"]["label"])
        record["relative_to_baseline"] = compare_traces(
            traces[label], baseline, dp,
            first_solver_valid=solver_valid_by_label[label],
            second_solver_valid=solver_valid_by_label[baseline_label],
        )
    return {
        "case_id": case["case_id"],
        "family": case["family"],
        "hdf5": str(h5_path),
        "particle_spacing_m": dp,
        "seed_count": int(seed_count),
        "frame_stride": int(frame_stride),
        "maximum_support_over_dp": float(maximum_support_over_dp),
        "boundary_sidecar": str(sidecar_path),
        "boundary_sidecar_audit": sidecar_audit,
        "settings": records,
    }


def _relative_path(path: Path, root: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve()))
    except ValueError:
        return str(Path(path).resolve())


def build_report(manifest_path: Path = DEFAULT_MANIFEST,
                 selected_ids: tuple[str, ...] = DEFAULT_CASES, *,
                 neighbours: Iterable[int] = (12, 24, 48),
                 regularization_over_dp: Iterable[float] = (0.05, 0.1, 0.2),
                 substeps: Iterable[int] = (1, 4),
                 full_factorial: bool = False,
                 seed_count: int = DEFAULT_COUNT,
                 frame_stride: int = DEFAULT_FRAME_STRIDE,
                 maximum_support_over_dp: float = DEFAULT_MAX_SUPPORT_OVER_DP,
                 sidecar_dir: Path | None = DEFAULT_SIDECAR_DIR) -> dict[str, Any]:
    """Run the bounded F1/F2/F3 CPU matrix and return a JSON-ready report."""
    manifest_path = Path(manifest_path).resolve()
    configurations = build_settings(
        neighbours, regularization_over_dp, substeps, full_factorial=full_factorial
    )
    selected = _load_cases(manifest_path, tuple(selected_ids))
    cases: dict[str, Any] = {}
    for case, h5_path in selected:
        sidecar_path = _sidecar_path(manifest_path, case, sidecar_dir)
        if not sidecar_path.is_file():
            raise FileNotFoundError(sidecar_path)
        case_report = run_case(
            case, h5_path, sidecar_path, settings=configurations,
            seed_count=seed_count, frame_stride=frame_stride,
            maximum_support_over_dp=maximum_support_over_dp,
        )
        case_report["hdf5"] = _relative_path(h5_path, manifest_path.parent)
        case_report["boundary_sidecar"] = _relative_path(sidecar_path, LAB)
        linked_sidecar = (manifest_path.parent / case["geometry"]["boundary_sidecar"]).resolve()
        case_report["boundary_sidecar_release_ref"] = case["geometry"]["boundary_sidecar"]
        case_report["boundary_sidecar_sha256"] = _sha256(sidecar_path)
        case_report["boundary_sidecar_release_sha256"] = _sha256(linked_sidecar)
        cases[case["case_id"]] = case_report

    all_records = [record for item in cases.values() for record in item["settings"]]
    perturbations = [record for record in all_records
                     if record["configuration"]["varied_parameter"] != "none"]
    finite_deltas = [record["relative_to_baseline"]["trajectory_delta_rmse_over_dp"]
                     for record in perturbations
                     if record["relative_to_baseline"]["trajectory_delta_rmse_over_dp"] is not None]
    return {
        "schema_version": 1,
        "scope": "R3 G2 wall-aware tracer neighbours/regularization/step sensitivity probe",
        "execution_status": "complete",
        "acceptance_status": "candidate_only",
        "non_claim": (
            "independent same-solver numerical sensitivity only; not external physical validation, "
            "not a material destination benchmark, and not a production default selection"
        ),
        "design": {
            "cases": list(selected_ids),
            "case_count": len(cases),
            "seed_count": int(seed_count),
            "frame_stride": int(frame_stride),
            "maximum_support_over_dp": float(maximum_support_over_dp),
            "factorial": bool(full_factorial),
            "one_factor_at_a_time": not bool(full_factorial),
            "setting_count_per_case": len(configurations),
            "total_run_count": len(cases) * len(configurations),
            "configurations": configurations,
            "baseline": dict(DEFAULT_BASELINE),
            "wall_visibility": True,
            "sidecar_directory": _relative_path(
                sidecar_dir or manifest_path.parent, LAB
            ),
            "sidecar_release_binding": "staged sidecar must match manifest-linked SHA256",
        },
        "sidecar_contract": {
            "required": True,
            "schema": "boundary-sidecar-v1",
            "coordinate_frame": "world",
            "time_axis": "must exactly match the solver HDF5 time axis",
            "geometry_status": "candidate finite triangles; open-face and implicit-cap policy remains unresolved",
        },
        "cases_reported": cases,
        "summary": {
            "case_count": len(cases),
            "total_run_count": len(all_records),
            "all_sidecars_time_aligned": all(
                item["boundary_sidecar_audit"].get("time_matches_solver", False)
                for item in cases.values()
            ),
            "all_sidecars_finite_and_nondegenerate": all(
                item["boundary_sidecar_audit"]["all_frames_finite"]
                and item["boundary_sidecar_audit"]["all_frames_nondegenerate"]
                for item in cases.values()
            ),
            "perturbation_count": len(perturbations),
            "max_trajectory_delta_from_baseline_over_dp": (
                float(max(finite_deltas)) if finite_deltas else None
            ),
        },
        "interpretation": {
            "neighbours": "changes the number of nearest velocity samples in the independent Shepard interpolant",
            "regularization_over_dp": "changes the inverse-distance denominator epsilon relative to spatial resolution",
            "substeps_per_interval": "changes Heun integration subdivision while keeping solver saved frames fixed",
            "comparison": "each perturbation is compared with the same-case baseline over common states where both interpolants are reliable and both solver reference identities remain valid",
            "sidecar_binding": "a staged sidecar is accepted only when its SHA256 equals the release-manifest-linked artifact",
            "decision": "do not select a global production setting from this small three-case candidate probe",
            "release_gate": "destination regions, explicit open/closed face policy, and external validation are still required",
        },
        "open_blockers": [
            "boundary semantic audit still flags implicit obstacle/baffle caps requiring an explicit policy",
            "material destination regions and task labels are not present in the development release",
            "only one representative F1/F2/F3 case and 16 seeds are used; this is not family coverage",
            "the probe compares against solver particle identity and does not establish physical truth",
        ],
    }


def _fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return "NA"
    return f"{float(value):.{digits}f}"


def render_conclusion_zh(report: dict[str, Any]) -> str:
    """Render a short Chinese, candidate-only handoff from a report."""
    design = report["design"]
    summary = report["summary"]
    lines = [
        "# R3 G2 wall-aware 示踪邻居数/正则化/积分步敏感性",
        "",
        "状态：**candidate-only；这轮只用于探路，不接受任何生产示踪配置为真值。**",
        "",
        "## 运行范围",
        "",
        f"在 F1/F2/F3 各一个代表案例上，使用已审计的 world-space boundary sidecar，"
        f"每个案例运行 {design['setting_count_per_case']} 个配置，共 {design['total_run_count']} 个 CPU 设置。"
        f"示踪点数为 {design['seed_count']}，保存帧 stride={design['frame_stride']}，"
        f"支持距离上限为 {design['maximum_support_over_dp']} dp。",
        "",
        "默认设计为 one-factor-at-a-time：基线是 `neighbours=24`、"
        "`regularization=0.1 dp`、每个保存区间 4 个 Heun 子步；"
        "邻居数、正则化系数和子步数分别做扰动。报告中的每一项还记录了相对同案例基线的轨迹差异。",
        "",
        "## 工程结果",
        "",
        f"- sidecar 时间轴对齐：{summary['all_sidecars_time_aligned']}；"
        f"有限且非退化：{summary['all_sidecars_finite_and_nondegenerate']}。",
        f"- 扰动配置数：{summary['perturbation_count']}；"
        f"相对基线的最大轨迹 RMSE 差异为 {_fmt(summary['max_trajectory_delta_from_baseline_over_dp'])} dp。",
        "- sidecar 通过 release manifest 链接的 SHA256 绑定；配置间差异只在双方插值可靠且 solver reference identity 有效的共同状态上计算。",
        "- 具体案例、每个配置的末端可靠率、质量加权误差、支持距离、穿墙拒绝数和运行时间均在机器可读 JSON 中保存。",
        "",
        "## 解释边界",
        "",
        "1. 邻居数、正则化和积分子步会改变独立示踪器的数值轨迹；这种差异是配置敏感性证据，不是物理误差界或收敛证明。",
        "2. sidecar 只提供候选有限三角面。开放面、障碍物/挡板隐式底部 cap 的语义仍需 policy；材料 destination region 也尚未定义。",
        "3. 这轮只有三个代表案例和 16 个示踪点，不能代表家族覆盖，也不能据此选出全局生产默认值。",
        "4. 当前比较仍是同一求解器导出与初始粒子身份轨迹的数值一致性检查，不是外部实验验证；solver-valid 掩码用于避免把身份失效后的状态纳入敏感性差异。",
        "",
        "## 下一步",
        "",
        "先补齐每个 boundary component 的 open/closed/rim/supporting policy 和 destination specification，"
        "再在更多分辨率、保存 cadence、示踪密度及已通过语义审计的案例上重复该矩阵；"
        "任何正式材料任务都应同时报告质量闭合、可靠率、支持距离、轨迹误差与目的地尾部统计。",
        "",
        "机器可读证据：`r3-g2-tracer-neighbour-sensitivity.json`。",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--sidecar-dir", type=Path, default=DEFAULT_SIDECAR_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--conclusion", type=Path, default=DEFAULT_CONCLUSION)
    parser.add_argument("--case", dest="cases", action="append", default=None)
    parser.add_argument("--neighbours", nargs="+", type=int, default=[12, 24, 48])
    parser.add_argument("--regularization-over-dp", nargs="+", type=float,
                        default=[0.05, 0.1, 0.2])
    parser.add_argument("--substeps", nargs="+", type=int, default=[1, 4])
    parser.add_argument("--full-factorial", action="store_true")
    parser.add_argument("--seed-count", type=int, default=DEFAULT_COUNT)
    parser.add_argument("--frame-stride", type=int, default=DEFAULT_FRAME_STRIDE)
    parser.add_argument("--maximum-support-over-dp", type=float,
                        default=DEFAULT_MAX_SUPPORT_OVER_DP)
    args = parser.parse_args()
    case_ids = tuple(args.cases) if args.cases else DEFAULT_CASES
    report = build_report(
        args.manifest.resolve(), case_ids,
        neighbours=tuple(args.neighbours),
        regularization_over_dp=tuple(args.regularization_over_dp),
        substeps=tuple(args.substeps), full_factorial=args.full_factorial,
        seed_count=args.seed_count, frame_stride=args.frame_stride,
        maximum_support_over_dp=args.maximum_support_over_dp,
        sidecar_dir=args.sidecar_dir.resolve() if args.sidecar_dir else None,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    args.conclusion.parent.mkdir(parents=True, exist_ok=True)
    args.conclusion.write_text(render_conclusion_zh(report))
    print(json.dumps({
        "report": str(args.report),
        "conclusion": str(args.conclusion),
        "cases": list(case_ids),
        "total_run_count": report["summary"]["total_run_count"],
        "acceptance_status": report["acceptance_status"],
    }, indent=2))


if __name__ == "__main__":
    main()
