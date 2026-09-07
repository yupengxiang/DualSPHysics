#!/usr/bin/env python3
"""Aggregate R3 G4 baseline runs without turning model failure into a gate."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
import string
from typing import Any

import h5py
import numpy as np


ROUTES = ("particle_mlp", "deepset_context", "local_interaction", "physics_residual")
SEEDS = (17, 29, 43)
LAB = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = LAB / "campaigns" / "v0.1-candidate" / "w00-inventory.json"
DEFAULT_MANIFEST = LAB / "release" / "v0.1-development" / "manifest.json"


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


def _valid_sidecar_provenance(entry: dict[str, Any], case_id: str) -> bool:
    """Check the provenance emitted by a sidecar-aware baseline rollout."""

    if entry.get("boundary_source") != "sidecar_world_triangles":
        return False
    if not bool(entry.get("boundary_available")):
        return False
    provenance = entry.get("boundary_provenance")
    if not isinstance(provenance, dict):
        return False
    if provenance.get("schema_version") != "boundary-sidecar-v1":
        return False
    if provenance.get("coordinate_frame") != "world" or provenance.get("case_id") != case_id:
        return False
    if not isinstance(provenance.get("path"), str) or not provenance["path"]:
        return False
    try:
        frame_count = int(provenance.get("frame_count", 0))
        triangle_count = int(provenance.get("triangle_count", 0))
    except (TypeError, ValueError):
        return False
    if frame_count != int(entry.get("frames_expected", 0)) + 1 or triangle_count < 1:
        return False
    source_hash = provenance.get("source_geometry_sha256")
    return (
        isinstance(source_hash, str)
        and len(source_hash) == 64
        and all(char in string.hexdigits for char in source_hash)
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _attribute_text(value: Any, default: str = "") -> str:
    """Normalize HDF5 string attributes for deterministic provenance checks."""

    if value is None:
        return default
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _load_release_checksums(checksum_path: Path, release_root: Path) -> tuple[dict[str, str], list[str]]:
    """Load and validate the release checksum index.

    ``checksums.sha256`` is part of the release contract, rather than an
    informational listing.  Keep the parser deliberately small and strict so
    that a malformed or ambiguous entry cannot silently turn into a pass.
    Paths are retained in POSIX, manifest-relative form because that is the
    representation used by ``manifest.json`` and rollout provenance.
    """

    checksum_path = Path(checksum_path)
    release_root = Path(release_root).resolve()
    if not checksum_path.is_file():
        return {}, [f"release checksum manifest is missing: {checksum_path}"]
    checksums: dict[str, str] = {}
    issues: list[str] = []
    try:
        lines = checksum_path.read_text().splitlines()
    except OSError as error:
        return {}, [f"release checksum manifest is unreadable: {error}"]
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        fields = line.split(maxsplit=1)
        if len(fields) != 2:
            issues.append(f"checksum manifest line {line_number} is malformed")
            continue
        digest, relative = fields
        relative = relative.lstrip("*")
        if len(digest) != 64 or any(char not in string.hexdigits for char in digest):
            issues.append(f"checksum manifest line {line_number} has an invalid SHA256")
            continue
        relative_path = Path(relative)
        if relative_path.is_absolute():
            issues.append(f"checksum manifest line {line_number} uses an absolute path")
            continue
        try:
            resolved = (release_root / relative_path).resolve()
            resolved.relative_to(release_root)
        except ValueError:
            issues.append(f"checksum manifest line {line_number} escapes release root")
            continue
        key = relative_path.as_posix()
        digest = digest.lower()
        previous = checksums.get(key)
        if previous is not None and previous != digest:
            issues.append(f"checksum manifest has conflicting entries for {key}")
            continue
        checksums[key] = digest
    return checksums, issues


def audit_sidecar_artifacts(
    entries_by_case: dict[str, list[dict[str, Any]]], manifest_path: Path,
) -> dict[str, Any]:
    """Bind rollout provenance to the actual release sidecar artifact.

    Result JSON is an untrusted derived artifact.  Checking only the copied
    provenance fields would allow a stale or substituted sidecar to satisfy
    the boundary gate.  This audit resolves the release manifest link,
    reopens the HDF5 sidecar, validates its schema/geometry counts and checks
    that every seed reported the exact manifest-relative path and source
    geometry hash.
    """

    manifest_path = Path(manifest_path).resolve()
    release_root = manifest_path.parent
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        return {"pass": False, "issues": [f"unreadable release manifest: {error}"], "cases": {}}
    records = {record.get("case_id"): record for record in manifest.get("cases", [])}
    checksum_path = release_root / "checksums.sha256"
    release_checksums, checksum_issues = _load_release_checksums(checksum_path, release_root)
    issues: list[str] = list(checksum_issues)
    case_audits: dict[str, Any] = {}
    for case_id, entries in sorted(entries_by_case.items()):
        case_issues: list[str] = []
        record = records.get(case_id)
        if record is None:
            case_issues.append("case is absent from release manifest")
        geometry = record.get("geometry", {}) if record else {}
        expected_ref = geometry.get("boundary_sidecar")
        if not isinstance(expected_ref, str) or not expected_ref:
            case_issues.append("release manifest has no boundary_sidecar link")
        expected_path = (release_root / expected_ref).resolve() if isinstance(expected_ref, str) else None
        path_in_release = False
        if expected_path is not None:
            try:
                expected_path.relative_to(release_root)
            except ValueError:
                case_issues.append("manifest boundary_sidecar escapes release root")
            else:
                path_in_release = True
        if expected_path is None or not path_in_release or not expected_path.is_file():
            case_issues.append("manifest-linked boundary sidecar is missing")

        provenance_values = [entry.get("boundary_provenance") for entry in entries]
        path_values = [value.get("path") if isinstance(value, dict) else None for value in provenance_values]
        if any(value != expected_ref for value in path_values):
            case_issues.append("result provenance path differs from release manifest link")
        actual_summary: dict[str, Any] = {}
        if expected_path is not None and path_in_release and expected_path.is_file():
            try:
                actual_summary["file_sha256"] = _sha256(expected_path)
                checksum_key = expected_path.relative_to(release_root).as_posix()
                expected_digest = release_checksums.get(checksum_key)
                actual_summary["release_checksum_sha256"] = expected_digest
                if expected_digest is None:
                    case_issues.append(
                        f"release checksum manifest has no entry for linked sidecar: {checksum_key}"
                    )
                elif expected_digest != actual_summary["file_sha256"]:
                    case_issues.append(
                        f"actual sidecar SHA256 differs from release checksum for {checksum_key}"
                    )
                with h5py.File(expected_path, "r") as sidecar:
                    required = ("time", "triangles_world", "triangle_mk", "triangle_type")
                    missing = [name for name in required if name not in sidecar]
                    if missing:
                        case_issues.append(f"sidecar missing datasets: {missing}")
                    else:
                        times = np.asarray(sidecar["time"][:], dtype=np.float64)
                        triangles = np.asarray(sidecar["triangles_world"][:], dtype=np.float64)
                        triangle_mk = np.asarray(sidecar["triangle_mk"][:])
                        triangle_type = np.asarray(sidecar["triangle_type"][:])
                        actual_summary = {
                            "file_sha256": actual_summary["file_sha256"],
                            "release_checksum_sha256": actual_summary["release_checksum_sha256"],
                            "schema_version": _attribute_text(sidecar.attrs.get("schema_version")),
                            "coordinate_frame": _attribute_text(sidecar.attrs.get("coordinate_frame")),
                            "case_id": _attribute_text(sidecar.attrs.get("case_id")),
                            "frame_count": int(len(times)),
                            "triangle_count": int(triangles.shape[1]) if triangles.ndim == 4 else 0,
                            "static_triangle_count": int(np.sum(triangle_type == 0)),
                            "moving_triangle_count": int(np.sum(triangle_type == 1)),
                            "source_vtk": _attribute_text(sidecar.attrs.get("source_vtk"), "unknown"),
                            "source_hdf5": _attribute_text(sidecar.attrs.get("source_hdf5"), "unknown"),
                            "source_geometry_sha256": _attribute_text(sidecar.attrs.get("source_geometry_sha256")),
                        }
                        if actual_summary["schema_version"] != "boundary-sidecar-v1":
                            case_issues.append("sidecar schema is not boundary-sidecar-v1")
                        if actual_summary["coordinate_frame"] != "world":
                            case_issues.append("sidecar coordinate frame is not world")
                        if actual_summary["case_id"] != case_id:
                            case_issues.append("sidecar case_id differs from result case")
                        if triangles.ndim != 4 or triangles.shape[2:] != (3, 3) or not np.all(np.isfinite(triangles)):
                            case_issues.append("sidecar triangles have invalid shape or non-finite values")
                        if len(triangle_mk) != actual_summary["triangle_count"] or len(triangle_type) != actual_summary["triangle_count"]:
                            case_issues.append("sidecar triangle labels do not match geometry")
                        if not np.all(np.isin(triangle_type, (0, 1))):
                            case_issues.append("sidecar triangle_type contains a non-boundary value")
                        provenance_fields = (
                            "schema_version", "coordinate_frame", "case_id", "frame_count",
                            "triangle_count", "static_triangle_count", "moving_triangle_count",
                            "source_vtk", "source_hdf5", "source_geometry_sha256",
                        )
                        # Every result is an independent, untrusted artifact.
                        # Comparing only the first seed would let a later seed
                        # carry stale geometry metadata while the aggregate
                        # still reports a passing artifact gate.
                        for index, provenance in enumerate(provenance_values, start=1):
                            if not isinstance(provenance, dict):
                                case_issues.append(f"result provenance {index} is not an object")
                                continue
                            for field in provenance_fields:
                                if provenance.get(field) != actual_summary[field]:
                                    case_issues.append(
                                        f"result provenance {index} {field} differs from actual sidecar"
                                    )
                            # Newer producers may include the artifact hash
                            # explicitly.  Validate it when present while
                            # retaining compatibility with already materialized
                            # reports; the release checksum remains mandatory.
                            if "file_sha256" in provenance and provenance.get("file_sha256") != actual_summary["file_sha256"]:
                                case_issues.append(
                                    f"result provenance {index} file_sha256 differs from actual sidecar"
                                )
            except (OSError, KeyError, ValueError) as error:
                case_issues.append(f"sidecar unreadable: {error}")
        case_audits[case_id] = {
            "manifest_link": expected_ref,
            "path": str(expected_path) if expected_path else None,
            "actual": actual_summary,
            "pass": not case_issues,
            "issues": case_issues,
        }
        issues.extend(f"{case_id}: {issue}" for issue in case_issues)
    return {"pass": bool(case_audits) and not issues, "issues": issues, "cases": case_audits}


def aggregate_route(route: str, runs: list[dict[str, Any]]) -> dict[str, Any]:
    route_runs = [run for run in runs if run.get("route") == route]
    combinations = [(int(run["seed"]), run.get("route")) for run in route_runs]
    case_ids = sorted({case_id for run in route_runs for case_id in run.get("test_rollout", {})})
    per_case = {}
    for case_id in case_ids:
        entries = [run["test_rollout"][case_id] for run in route_runs if case_id in run.get("test_rollout", {})]
        first = entries[0]
        provenance_by_seed = {
            str(run["seed"]): run["test_rollout"][case_id].get("boundary_provenance")
            for run in route_runs if case_id in run.get("test_rollout", {})
        }
        provenance_keys = {
            json.dumps(value, sort_keys=True, separators=(",", ":"))
            for value in provenance_by_seed.values()
        }
        boundary_provenance_consistent = len(provenance_keys) == 1
        boundary_provenance_valid = all(
            _valid_sidecar_provenance(entry, case_id) for entry in entries
        )
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
            "boundary_provenance_by_seed": provenance_by_seed,
            "boundary_provenance_consistent": boundary_provenance_consistent,
            "boundary_provenance_valid": boundary_provenance_valid,
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


def conclusion(report: dict[str, Any], report_name: str = "r3-g4-baseline-audit.json") -> str:
    route_rows = []
    for route, value in report["routes"].items():
        macro = value["macro_position_rmse_over_dp"]["bootstrap"]
        route_rows.append(f"| {route} | {value['run_count']} | {value['seeds']} | {macro['estimate'] if macro['estimate'] is not None else 'n/a'} | {macro['q025'] if macro['q025'] is not None else 'n/a'}–{macro['q975'] if macro['q975'] is not None else 'n/a'} |")
    boundary_gate = bool(report.get("boundary_geometry_gate"))
    if boundary_gate:
        status = "development-only；已执行 sidecar-aware 边界输入，但这仍不是正式学习排行榜或物理验收。"
        boundary_note = "所有被评测 test cases 都通过了 sidecar schema、world 坐标、时间轴、三角形 provenance 和 per-seed 一致性检查；模型当前使用每一帧的有限三角形 AABB 摘要。"
        next_step = "下一步应验证三角形语义/可见性并补齐 T2/T3/T4；之后才考虑三维 F6 的 coupled body-state model。"
    else:
        status = "development-only；基线路线和指标闭环已执行，但边界 sidecar 输入契约未通过，因此不能宣布正式学习排行榜或物理验收。"
        boundary_note = "边界几何 availability/provenance gate 未通过；缺失 sidecar 不会被零向量伪装成已提供几何。"
        next_step = "下一步应先补齐并审计边界 sidecar，再复跑相同 matrix；之后才考虑三维 F6 的 coupled body-state model。"
    route_table = "\n".join(route_rows)
    return f"""# R3 G4 结论：因果输入与多路线学习基线

状态：**{status}**

## 路线与统一口径

| 路线 | runs | seeds | case-macro position RMSE/dp | case bootstrap 95% |
|---|---:|---|---:|---:|
{route_table}

所有学习路线都使用初始质量加权 COM、统一的 solver velocity 状态（训练使用当前帧速度，rollout 从帧 0 速度开始并只消费自己的下一帧速度）、不依赖文件终点的 elapsed time，以及相同的 `8*tanh(raw/8)` 平滑输出上限。位置、速度和 COM 均采用向量范数 RMSE；bootstrap 的重采样单位是物理案例而不是帧。

常速度结果仅作为弱、确定性的参照。学习器相对常速度的退化率逐案例报告，但**不作为场景准入门槛**；困难且可信的案例仍应保留。

## 因果输入与已知限制

当前 pilot 的 F2 提供当前时刻的规定杯体控制曲线，F1/F3 没有 control group；未来流体状态、未来密度/压力和自由刚体未来轨迹没有进入 rollout。密度、压力、质量仅作为初始属性。{boundary_note}

本轮只评测 T1 numerical particle rollout。T2 material transport、T3 external observables 和 F6 coupled free-body route 不在该实验中打分。

## 学习曲线和下一步

每个 route/seed 最多 8 epochs，至少 3 epochs；以 validation autonomous rollout 的 case macro RMSE、patience=2 和 min-delta 作为停止与 checkpoint 选择规则，并在机器可读报告中保存每一 epoch 曲线。{next_step}

机器可读明细见 `{report_name}`；实际运行入口和 GPU 分配见 `r3_g4_run_manifest.json`。
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--run-manifest", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
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
    configured_routes = tuple(config.get("routes", ROUTES))
    configured_seeds = tuple(int(seed) for seed in config.get("seeds", SEEDS))
    if not configured_routes or len(set(configured_routes)) != len(configured_routes):
        raise ValueError("config routes must be a non-empty list of unique route names")
    if not configured_seeds or len(set(configured_seeds)) != len(configured_seeds):
        raise ValueError("config seeds must be a non-empty list of unique integers")
    expected = [(route, seed) for route in configured_routes for seed in configured_seeds]
    gpu_audit = audit_gpu_manifest(run_manifest, config, inventory, expected)
    routes = {route: aggregate_route(route, runs) for route in configured_routes}
    all_case_entries = [entry for route in routes.values() for entry in route["per_case"].values()]
    # Build this map directly from raw test rollouts.  The route rows above
    # remain the report source of truth; this map is solely for artifact
    # binding against the release manifest.
    entries_by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        for case_id, entry in run.get("test_rollout", {}).items():
            row = dict(entry)
            row["case_id"] = case_id
            entries_by_case[case_id].append(row)
    sidecar_audit = audit_sidecar_artifacts(entries_by_case, args.manifest)
    boundary_geometry_gate = bool(all_case_entries) and all(
        entry["boundary_available"]
        and entry["boundary_provenance_valid"]
        and entry["boundary_provenance_consistent"]
        for entry in all_case_entries
    ) and bool(sidecar_audit["pass"])
    open_blockers = []
    if not boundary_geometry_gate:
        open_blockers.append(
            "boundary sidecar geometry/provenance gate is false; linked sidecars must be schema-valid, world-frame, time-aligned, and consistent across seeds"
        )
    open_blockers.extend([
        "only T1 particle rollout is scored; material transport and external observable tracks remain separate",
        "F6 free-body case has no fluid state in the pilot and is excluded until a coupled body-state route exists",
    ])
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
            "release_manifest": str(args.manifest.resolve()),
            "sidecar_artifact_audit": sidecar_audit,
            "allowed_gpu_indices": sorted(int(value) for value in config.get("allowed_gpu_indices", [])),
            "runs": physical_runs,
        },
        "run_count": len(runs), "expected_run_count": len(expected),
        "route_seed_gate": sorted(combinations) == sorted(expected) and len(set(combinations)) == len(combinations),
        "routes": routes,
        "case_count_per_route": {route: len(value["per_case"]) for route, value in routes.items()},
        "boundary_geometry_gate": boundary_geometry_gate,
        "nonfinite_rollout_gate": all(all(status == "completed" for status in entry["status_by_seed"].values()) for entry in all_case_entries),
        "physics_budget": {
            "status": "diagnostic_only",
            "mass_identity_preservation_reported": True,
            "predicted_density_pressure": False,
            "material_transport_scored": False,
        },
        "degradation_policy": "diagnostic_per_case; never a physical-scene admission gate",
        "formal_ready": False,
        "open_blockers": open_blockers,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    args.conclusion.parent.mkdir(parents=True, exist_ok=True)
    args.conclusion.write_text(conclusion(report, args.output.name))
    print(json.dumps({"run_count": len(runs), "route_seed_gate": report["route_seed_gate"], "physical_gpu_gate": report["run_manifest"]["physical_gpu_gate"], "artifact_provenance_gate": report["run_manifest"]["artifact_provenance_gate"], "boundary_geometry_gate": report["boundary_geometry_gate"], "routes": {k: v["macro_position_rmse_over_dp"]["bootstrap"] for k, v in routes.items()}}, indent=2))


if __name__ == "__main__":
    main()
