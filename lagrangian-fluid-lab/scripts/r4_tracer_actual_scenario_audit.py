#!/usr/bin/env python3
"""Independent CPU/static contract audit for actual tracer scenarios.

This audit deliberately sits beside the tracer and G4 implementations.  It
does not change either implementation, does not import torch, and never
launches GenCase, DualSPHysics, CUDA, or a GPU job.  The input is the already
materialized development release: the manifest, normalized HDF5 trajectories,
boundary sidecars, and the candidate boundary-component policy.

The audit has two jobs:

* inspect the artifacts that an actual scenario would hand to a tracer or G4
  consumer; and
* inspect the relevant source contracts so that a structurally valid artifact
  cannot hide a missing producer/consumer interface.

It intentionally reports candidate-only evidence as candidate-only.  In
particular, a finite sidecar is not treated as proof that the material
trajectory was wall-aware, and an initial ``Mk`` label is not promoted to
physical material lineage.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import h5py
import numpy as np


LAB = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = LAB / "release" / "v0.1-development" / "manifest.json"
DEFAULT_REPORT = LAB / "campaigns" / "v0.1-candidate" / "r4-tracer-actual-scenario-audit.json"
DEFAULT_MARKDOWN = LAB / "campaigns" / "v0.1-candidate" / "R4-TRACER-ACTUAL-SCENARIO-AUDIT.md"

SCHEMA_VERSION = "r4-tracer-actual-scenario-audit-v1"
REQUIRED_ROOT_ATTRS = (
    "schema_version",
    "case_id",
    "family",
    "solver",
    "identity_key",
    "trajectory_semantics",
    "world_frame",
    "time_units",
    "length_units",
    "mass_units",
)
REQUIRED_TRAJECTORY_DATASETS = (
    "time",
    "particle_id",
    "particle_zone",
    "valid",
    "position",
    "velocity",
    "density",
    "pressure",
    "mass",
    "type",
    "mk",
)
REQUIRED_MATERIAL_DATASETS = (
    "tracer_id",
    "seed_particle_id",
    "seed_particle_zone",
    "source_label",
    "mass_weight",
    "valid",
    "position",
)
SUPPORT_DATASETS = (
    "nearest_support_distance",
    "support_gate_pass",
    "effective_sample_size",
    "support_geometry_rank",
    "support_anisotropy",
    "interpolation_reconstruction_error_mps",
)
BOUNDARY_RIM_POLICIES = {
    "exclude_open_face_rim",
    "review_required_implicit_cap",
}
BOUNDARY_FACES = {"bottom", "left", "right", "front", "back", "top"}
SUBSTEP_KEYS = (
    "substeps_per_interval",
    "integration_substeps",
    "tracer_substeps_per_saved_interval",
    "substeps_per_saved_interval",
)


def _text(value: Any, default: str = "") -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return default if value is None else str(value)


def _finite_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if np.isfinite(result) else None


def _json_value(value: Any) -> Any:
    """Convert NumPy/HDF5 scalar values without emitting non-JSON values."""
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.ndarray):
        return [_json_value(item) for item in value.tolist()]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def _resolve_under(root: Path, base: Path, reference: Any) -> Path:
    if not isinstance(reference, str) or not reference.strip():
        raise ValueError("path reference must be a non-empty string")
    candidate = (base / reference).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"path escapes release root: {reference!r}") from exc
    return candidate


def _close(left: float, right: float, *, rtol: float = 1e-8, atol: float = 1e-8) -> bool:
    return bool(np.isclose(float(left), float(right), rtol=rtol, atol=atol))


def _strict_time(values: np.ndarray) -> bool:
    values = np.asarray(values, dtype=float)
    return bool(
        values.ndim == 1
        and len(values) >= 2
        and np.all(np.isfinite(values))
        and np.all(np.diff(values) > 0.0)
    )


def _mass_rows(weights: np.ndarray, sources: np.ndarray, mask: np.ndarray) -> dict[str, dict[str, Any]]:
    weights = np.asarray(weights, dtype=float)
    sources = np.asarray(sources)
    mask = np.asarray(mask, dtype=bool)
    rows: dict[str, dict[str, Any]] = {}
    for source in sorted(int(value) for value in np.unique(sources)):
        selected = mask & (sources == source)
        rows[str(source)] = {
            "tracer_count": int(selected.sum()),
            "mass_kg": float(np.sum(weights[selected], dtype=np.float64)),
        }
    return rows


def _function_map(path: Path) -> tuple[str, dict[str, ast.AST], str | None]:
    if not path.is_file():
        return "", {}, "file_missing"
    source = path.read_text(errors="replace")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return source, {}, f"syntax_error:{exc.msg}"
    functions: dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.setdefault(node.name, node)
    return source, functions, None


def _function_source(source: str, node: ast.AST | None) -> str:
    if node is None or not hasattr(node, "lineno"):
        return ""
    lines = source.splitlines()
    start = int(node.lineno) - 1
    end = int(getattr(node, "end_lineno", node.lineno))
    return "\n".join(lines[start:end])


def _line_ref(path: Path, root: Path, source: str, needle: str) -> str:
    line = next((index for index, value in enumerate(source.splitlines(), 1) if needle in value), None)
    suffix = f":{line}" if line is not None else ""
    return f"{_relative(path, root)}{suffix}"


def _static_inventory(lab_root: Path) -> dict[str, Any]:
    """Inspect the source contracts without importing production modules."""
    tracer_path = lab_root / "scripts" / "passive_tracers.py"
    trajectory_path = lab_root / "scripts" / "trajectory_io.py"
    material_writer_path = lab_root / "scripts" / "w11_build_pilot.py"
    g4_path = lab_root / "experiments" / "r3_g4_baselines.py"
    transport_path = lab_root / "scripts" / "transport_metrics.py"
    convergence_path = lab_root / "scripts" / "r3_g2_tracer_convergence.py"
    protocol_path = lab_root / "protocol" / "trajectory-v0.1.md"

    tracer_source, tracer_functions, tracer_error = _function_map(tracer_path)
    trajectory_source, trajectory_functions, trajectory_error = _function_map(trajectory_path)
    writer_source, writer_functions, writer_error = _function_map(material_writer_path)
    g4_source, g4_functions, g4_error = _function_map(g4_path)
    transport_source, transport_functions, transport_error = _function_map(transport_path)
    convergence_source, convergence_functions, convergence_error = _function_map(convergence_path)
    protocol_source = protocol_path.read_text(errors="replace") if protocol_path.is_file() else ""

    def function_record(source: str, functions: Mapping[str, ast.AST], names: Iterable[str]) -> dict[str, Any]:
        output = {}
        for name in names:
            node = functions.get(name)
            function_text = _function_source(source, node)
            output[name] = {
                "present": node is not None,
                "line": int(node.lineno) if node is not None and hasattr(node, "lineno") else None,
                "text_checks": {
                    "frame_stride": "frame_stride" in function_text,
                    "substeps_per_interval": "substeps_per_interval" in function_text,
                    "support_gate": "support_gate" in function_text,
                    "barrier_provider": "barrier_provider" in function_text,
                    "material": "material" in function_text,
                    "stable_fluid_selection": "stable = np.all(fluid, axis=0)" in function_text,
                    "open_faces": "open_faces" in function_text,
                },
            }
        return output

    tracer_caps = {
        "initial_mk_source_stratification": "h5[\"mk\"][0, candidates]" in tracer_source,
        "initial_mass_assignment": "mass_weight" in _function_source(tracer_source, tracer_functions.get("weighted_stratified_seeds")),
        "heun_integrator": "0.5 * np.nan_to_num(v0 + v1)" in tracer_source,
        "saved_cadence_and_substeps_are_separate": (
            "frame_stride" in _function_source(tracer_source, tracer_functions.get("advect_hdf5"))
            and "substeps_per_interval" in _function_source(tracer_source, tracer_functions.get("advect_hdf5"))
        ),
        "support_quality_gate": "_support_gate_pass" in tracer_source and "support_gate" in tracer_source,
        "finite_wall_visibility": "segment_visibility" in tracer_source,
        "swept_wall_check": "spacetime_swept_wall_blocked" in tracer_source,
        "rigid_motion_interpolation": "quaternion_slerp" in tracer_source,
    }
    trajectory_caps = {
        "compound_key_frame_alignment": "key_to_index" in trajectory_source and "(zone, pid)" in trajectory_source,
        "direct_converter_writes_material_group": "create_group(\"material\")" in trajectory_source,
        "direct_converter_writes_protocol_units": all(
            token in _function_source(trajectory_source, trajectory_functions.get("create_partial"))
            for token in ("world_frame", "time_units", "length_units", "mass_units")
        ),
    }
    writer_caps = {
        "material_writer_present": "augment_material" in writer_functions,
        "material_writer_persists_support_distance": "nearest_support_distance" in writer_source,
        "material_writer_persists_support_gate": "support_gate_pass" in writer_source,
        "material_writer_persists_integration_substeps": any(
            key in writer_source for key in SUBSTEP_KEYS
        ),
        "material_writer_passes_substeps_to_advector": "substeps_per_interval=" in writer_source,
        "material_writer_passes_barrier_provider": "barrier_provider=" in writer_source,
    }
    g4_load_source = _function_source(g4_source, g4_functions.get("_load_case"))
    g4_boundary_source = _function_source(g4_source, g4_functions.get("_boundary_features"))
    g4_component_source = _function_source(g4_source, g4_functions.get("_boundary_component_features"))
    g4_caps = {
        "future_state_rejection": "validate_model_input_contract" in g4_source and "future fluid/free-body" in g4_source,
        "stable_fluid_identity_filter": "stable = np.all(fluid, axis=0)" in g4_load_source,
        "loads_initial_density_pressure_mass": all(
            token in g4_load_source for token in ("density0", "pressure0", "mass0")
        ),
        "loads_material_group": any(
            token in g4_load_source for token in ("h5[\"material", "h5.get(\"material", "material_group")
        ),
        "sidecar_validation": "_validate_boundary_sidecar" in g4_source,
        "component_geometry_features": "distance_to_boundary_component_m" in g4_source,
        "open_face_policy_input": "open_faces" in g4_component_source or "open_faces" in g4_boundary_source,
        "legacy_aabb_fallback": "legacy-static-boundary-summary" in g4_boundary_source,
        "boundary_input_has_wall_velocity": "wall_velocity_mps" in g4_source,
    }
    transport_caps = {
        "explicit_destination_validation": "destinations must be a non-empty list" in transport_source,
        "initial_mass_denominator": "initial_mass" in _function_source(transport_source, transport_functions.get("audit_transport")),
        "unclassified_category": "in_domain_unclassified" in transport_source,
        "closed_loss_category": "numerical_loss" in transport_source,
        "open_lifecycle_uses_unknown_exit": 'missing_name = "numerical_loss" if lifecycle == "closed" else "unknown_exit"' in transport_source,
        "destination_frame_transform": "positions_in_frame" in transport_source,
    }
    comparison_source = _function_source(convergence_source, convergence_functions.get("compare_traces"))
    resolution_comparison_caps = {
        "compare_traces_present": "compare_traces" in convergence_functions,
        "rowwise_position_delta": 'first["position"]' in comparison_source and 'second["position"]' in comparison_source,
        "stable_key_guard": any(
            token in comparison_source
            for token in ("stable_key", "tracer_id", "particle_id", "resolution_group_id")
        ),
        "same_case_solver_mask_support": "solver_valid_mask_applied" in comparison_source,
    }
    protocol_caps = {
        token: token in protocol_source
        for token in (
            "material/",
            "mass_weight",
            "saved velocity cadence",
            "integration substeps",
            "visibility is recomputed",
            "open-face",
            "in_domain_unclassified",
            "numerical_loss",
            "cross-resolution",
        )
    }

    synthetic_paths = (
        "tests/test_passive_tracers.py",
        "tests/test_trajectory_io.py",
        "tests/test_r3_g2_tracer_visibility.py",
        "tests/test_r3_g2_tracer_convergence.py",
        "tests/test_r3_geometry_contracts.py",
        "tests/test_c1_c2_production_contracts.py",
    )
    synthetic = []
    for relative in synthetic_paths:
        path = lab_root / relative
        source = path.read_text(errors="replace") if path.is_file() else ""
        synthetic.append({
            "path": relative,
            "present": path.is_file(),
            "checks": {
                "seed_or_mass": any(token in source for token in ("weighted", "mass_weight", "source")),
                "cadence_or_substeps": any(token in source for token in ("frame_stride", "substeps", "cadence")),
                "support_failure": any(token in source for token in ("support_gate", "support", "reliable")),
                "wall_or_opening": any(token in source for token in ("wall", "barrier", "opening")),
                "g4": "g4" in source.lower() or "boundary_component" in source,
                "failure_population": any(token in source for token in ("failure_count", "failed", "failure_fraction")),
            },
        })

    gaps = []
    if not trajectory_caps["direct_converter_writes_material_group"]:
        gaps.append({
            "id": "trajectory_io_no_material_group",
            "severity": "P1",
            "evidence": _line_ref(trajectory_path, lab_root, trajectory_source, "def create_partial"),
            "finding": "直接 CSV→HDF5 转换器只建立 solver 数值身份轴，不建立 protocol 所需的 material/ 组。",
            "minimum_interface": "材料 seed/source/质量权重/valid 轨迹必须由显式 material producer 写入；本轮不改生产代码。",
        })
    if not trajectory_caps["direct_converter_writes_protocol_units"]:
        gaps.append({
            "id": "trajectory_io_units_only_added_by_later_wrapper",
            "severity": "P1",
            "evidence": _line_ref(trajectory_path, lab_root, trajectory_source, "h5.attrs.update"),
            "finding": "trajectory_io.create_partial 本身没有写入 world_frame/time_units/length_units/mass_units；实际 release 依靠 W11 wrapper 后补。",
            "minimum_interface": "让 converter 的 protocol output contract 与 materialization wrapper 分层且显式，避免直接消费者拿到不完整 HDF5。",
        })
    if not writer_caps["material_writer_persists_integration_substeps"]:
        gaps.append({
            "id": "material_artifact_no_substep_provenance",
            "severity": "P1",
            "evidence": _line_ref(material_writer_path, lab_root, writer_source, "def augment_material"),
            "finding": "当前 material writer 调用 advect_hdf5 时没有保存每个 saved interval 使用的积分子步数。",
            "minimum_interface": "在 material attrs/manifest 中持久化 integration_method、substeps_per_saved_interval 和实际 substep dt。",
        })
    if not writer_caps["material_writer_passes_barrier_provider"]:
        gaps.append({
            "id": "material_writer_not_wall_aware",
            "severity": "P1",
            "evidence": _line_ref(material_writer_path, lab_root, writer_source, "traced = advect_hdf5"),
            "finding": "现有 W11 material writer 未把 sidecar barrier_provider 传给 advector；artifact 中 wall_visibility 也不是 true。",
            "minimum_interface": "实际场景 material materialization 必须显式链接 sidecar、open-face policy 和 barrier provider。",
        })
    if not g4_caps["loads_material_group"]:
        gaps.append({
            "id": "g4_loader_does_not_load_material_group",
            "severity": "P1",
            "evidence": _line_ref(g4_path, lab_root, g4_source, "def _load_case"),
            "finding": "G4 _load_case 只读取 stable solver fluid identity 和 initial density/pressure/mass，不读取 material/ seed/source/mass_weight。",
            "minimum_interface": "material transport 不能复用 particle rollout loader；需新增显式 material input contract。",
        })
    if not g4_caps["open_face_policy_input"]:
        gaps.append({
            "id": "g4_boundary_input_omits_open_face_semantics",
            "severity": "P1",
            "evidence": _line_ref(g4_path, lab_root, g4_source, "def boundary_component_features"),
            "finding": "G4 component features 有距离/法向/Type/壁速度，但没有 open/closed/rim/supporting policy 字段。",
            "minimum_interface": "sidecar component 到 G4 的输入必须携带可审计的 open-face/rim/supporting 语义，而非只传几何摘要。",
        })
    if g4_caps["legacy_aabb_fallback"]:
        gaps.append({
            "id": "g4_legacy_aabb_is_not_wall_contract",
            "severity": "P2",
            "evidence": _line_ref(g4_path, lab_root, g4_source, "legacy-static-boundary-summary"),
            "finding": "无 sidecar 时 G4 仍可从静态 AABB 得到 boundary_available；AABB 不能识别开口/挡板拓扑。",
            "minimum_interface": "正式 wall-aware material target 必须拒绝 legacy AABB-only geometry，或明确标记为 non-identifiable。",
        })
    if transport_caps["open_lifecycle_uses_unknown_exit"]:
        gaps.append({
            "id": "open_lifecycle_exit_reason_not_protocol_numerical_loss",
            "severity": "P2",
            "evidence": _line_ref(transport_path, lab_root, transport_source, "unknown_exit"),
            "finding": "现有 transport_metrics 对 open lifecycle 把失效 mass 命名为 unknown_exit；trajectory-v0.1 的 closure 必须显式处理 numerical_loss/退出语义。",
            "minimum_interface": "为 open-face 穿出提供有符号事件/exit reason；不能把末帧缺失自动解释成 numerical loss 或 physical exit。",
        })
    if resolution_comparison_caps["rowwise_position_delta"] and not resolution_comparison_caps["stable_key_guard"]:
        gaps.append({
            "id": "cross_resolution_compare_has_no_stable_key_guard",
            "severity": "P1",
            "evidence": _line_ref(convergence_path, lab_root, convergence_source, "def compare_traces"),
            "finding": "现有 compare_traces 按 trace array 位置做差，API 没有 stable material key 或 resolution-group guard；它只能安全用于同一 HDF5/同一 seed axis 的 cadence/substep 对照。",
            "minimum_interface": "跨分辨率比较必须改为 source×destination mass aggregate 或显式稳定 key；本轮只在 audit negative control 中执行该禁令。",
        })

    return {
        "tracer": {
            "path": _relative(tracer_path, lab_root),
            "sha256": _sha256(tracer_path),
            "parse_error": tracer_error,
            "functions": function_record(
                tracer_source,
                tracer_functions,
                ("advect_hdf5", "weighted_stratified_seeds", "deterministic_seeds", "shepard_velocity_with_diagnostics", "segment_visibility", "spacetime_swept_wall_blocked"),
            ),
            "capabilities": tracer_caps,
        },
        "trajectory_io": {
            "path": _relative(trajectory_path, lab_root),
            "sha256": _sha256(trajectory_path),
            "parse_error": trajectory_error,
            "functions": function_record(trajectory_source, trajectory_functions, ("create_partial", "write_frames", "convert_streaming")),
            "capabilities": trajectory_caps,
        },
        "material_writer": {
            "path": _relative(material_writer_path, lab_root),
            "sha256": _sha256(material_writer_path),
            "parse_error": writer_error,
            "functions": function_record(writer_source, writer_functions, ("augment_material", "audit_case")),
            "capabilities": writer_caps,
        },
        "g4_loader": {
            "path": _relative(g4_path, lab_root),
            "sha256": _sha256(g4_path),
            "parse_error": g4_error,
            "functions": function_record(g4_source, g4_functions, ("_load_case", "_boundary_features", "_boundary_component_series", "boundary_component_features", "validate_model_input_contract")),
            "capabilities": g4_caps,
        },
        "transport_metrics": {
            "path": _relative(transport_path, lab_root),
            "sha256": _sha256(transport_path),
            "parse_error": transport_error,
            "functions": function_record(transport_source, transport_functions, ("validate_transport_spec", "audit_transport")),
            "capabilities": transport_caps,
        },
        "resolution_comparison": {
            "path": _relative(convergence_path, lab_root),
            "sha256": _sha256(convergence_path),
            "parse_error": convergence_error,
            "functions": function_record(convergence_source, convergence_functions, ("compare_traces",)),
            "capabilities": resolution_comparison_caps,
        },
        "trajectory_protocol": {
            "path": _relative(protocol_path, lab_root),
            "sha256": _sha256(protocol_path),
            "capabilities": protocol_caps,
        },
        "existing_synthetic_tests": synthetic,
        "open_interface_gaps": gaps,
    }


def _audit_sidecar(
    sidecar_path: Path | None,
    solver_time: np.ndarray,
    case_id: str,
    release_root: Path,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": _relative(sidecar_path, release_root) if sidecar_path is not None else None,
        "present": bool(sidecar_path is not None and sidecar_path.is_file()),
        "sha256": _sha256(sidecar_path) if sidecar_path is not None else None,
        "schema_version": None,
        "coordinate_frame": None,
        "case_id": None,
        "time_match": False,
        "triangle_count": 0,
        "component_count": 0,
        "component_label_field": None,
        "component_labels": [],
        "finite_triangles": False,
        "nondegenerate_triangles": False,
        "structural_pass": False,
        "error": None,
    }
    if sidecar_path is None:
        result["error"] = "no_boundary_sidecar_link"
        return result
    if not sidecar_path.is_file():
        result["error"] = "linked_boundary_sidecar_missing"
        return result
    try:
        with h5py.File(sidecar_path, "r") as sidecar:
            required = ("time", "triangles_world", "triangle_mk", "triangle_type")
            missing = [name for name in required if name not in sidecar]
            if missing:
                raise ValueError(f"missing datasets: {missing}")
            result["schema_version"] = _text(sidecar.attrs.get("schema_version"))
            result["coordinate_frame"] = _text(sidecar.attrs.get("coordinate_frame"))
            result["case_id"] = _text(sidecar.attrs.get("case_id"))
            times = np.asarray(sidecar["time"][:], dtype=float)
            triangles = np.asarray(sidecar["triangles_world"][:], dtype=float)
            kinds = np.asarray(sidecar["triangle_type"][:])
            labels = np.asarray(
                sidecar["triangle_component"][:] if "triangle_component" in sidecar else sidecar["triangle_mk"][:]
            )
            result["component_label_field"] = "triangle_component" if "triangle_component" in sidecar else "triangle_mk"
            result["triangle_count"] = int(triangles.shape[1]) if triangles.ndim >= 2 else 0
            result["component_labels"] = [int(value) for value in np.unique(labels)] if labels.size else []
            result["component_count"] = len(result["component_labels"])
            if (
                times.ndim != 1
                or len(times) < 2
                or not _strict_time(times)
                or not _strict_time(np.asarray(solver_time, dtype=float))
                or len(times) != len(solver_time)
            ):
                raise ValueError("sidecar and solver time axes are not valid or have different lengths")
            result["time_match"] = bool(np.allclose(times, solver_time, rtol=0.0, atol=1e-9))
            if not result["time_match"]:
                raise ValueError("sidecar time axis differs from solver")
            if triangles.ndim != 4 or triangles.shape[0] != len(times) or triangles.shape[2:] != (3, 3):
                raise ValueError("triangles_world must have shape [T,N,3,3]")
            if triangles.shape[1] < 1 or len(kinds) != triangles.shape[1] or len(labels) != triangles.shape[1]:
                raise ValueError("triangle labels do not match geometry")
            result["finite_triangles"] = bool(np.all(np.isfinite(triangles)))
            edge1 = triangles[:, :, 1] - triangles[:, :, 0]
            edge2 = triangles[:, :, 2] - triangles[:, :, 0]
            area2 = np.linalg.norm(np.cross(edge1, edge2), axis=-1)
            result["nondegenerate_triangles"] = bool(np.all(area2 > 1e-12))
            valid_types = bool(np.all(np.isin(kinds, (0, 1))))
            result["structural_pass"] = bool(
                result["schema_version"] == "boundary-sidecar-v1"
                and result["coordinate_frame"] == "world"
                and result["case_id"] == case_id
                and result["time_match"]
                and result["finite_triangles"]
                and result["nondegenerate_triangles"]
                and valid_types
            )
    except (OSError, ValueError, KeyError) as exc:
        result["error"] = str(exc)
    return result


def _audit_boundary_policy(
    policy: Mapping[str, Any] | None,
    case_id: str,
    sidecar: Mapping[str, Any],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "policy_present": False,
        "policy_acceptance_status": None,
        "case_present": False,
        "structural_pass": False,
        "review_required": False,
        "component_count": 0,
        "components": [],
        "sidecar_component_count_matches": None,
        "explicit_mkbound_to_mk_mapping": False,
        "mapping_status": "not_available",
        "candidate_open_face_semantics_pass": False,
        "formal_wall_visibility_admitted": False,
        "error": None,
    }
    if policy is None:
        result["error"] = "boundary_component_policy_missing"
        return result
    result["policy_present"] = True
    result["policy_acceptance_status"] = _text(policy.get("acceptance_status"), "")
    rows = policy.get("cases")
    if not isinstance(rows, list):
        result["error"] = "boundary_component_policy_cases_missing"
        return result
    row = next((item for item in rows if isinstance(item, dict) and item.get("case_id") == case_id), None)
    if row is None:
        result["error"] = "case_missing_from_boundary_component_policy"
        return result
    result["case_present"] = True
    components = row.get("components")
    if not isinstance(components, list) or not components:
        result["error"] = "policy_case_components_missing"
        return result
    result["component_count"] = len(components)
    errors = []
    component_output = []
    explicit_mapping = False
    review_required = bool(row.get("review_required", False))
    for index, component in enumerate(components):
        if not isinstance(component, dict):
            errors.append(f"components[{index}] is not an object")
            continue
        required = ("component_id", "mkbound", "role", "open_faces", "rim_policy", "supporting_component", "review_status")
        missing = [name for name in required if name not in component]
        if missing:
            errors.append(f"components[{index}] missing {missing}")
        open_faces = component.get("open_faces")
        if not isinstance(open_faces, list) or any(face not in BOUNDARY_FACES for face in open_faces):
            errors.append(f"components[{index}] has invalid open_faces")
        if component.get("rim_policy") not in BOUNDARY_RIM_POLICIES:
            errors.append(f"components[{index}] has invalid rim_policy")
        if component.get("supporting_component") is not None and not isinstance(component.get("supporting_component"), dict):
            errors.append(f"components[{index}] has invalid supporting_component")
        if component.get("review_status") not in {"candidate_unresolved", "pending_human_or_rule_confirmation"}:
            errors.append(f"components[{index}] has invalid review_status")
        if any(key in component for key in ("mk", "triangle_mk", "solver_mk")):
            explicit_mapping = True
        if component.get("review_status") != "candidate_unresolved" or component.get("rim_policy") == "review_required_implicit_cap":
            review_required = True
        component_output.append({
            "component_id": component.get("component_id"),
            "mkbound": component.get("mkbound"),
            "role": component.get("role"),
            "open_faces": list(open_faces) if isinstance(open_faces, list) else [],
            "rim_policy": component.get("rim_policy"),
            "supporting_component": component.get("supporting_component"),
            "review_status": component.get("review_status"),
        })
    result["components"] = component_output
    result["review_required"] = review_required
    result["explicit_mkbound_to_mk_mapping"] = explicit_mapping
    sidecar_count = sidecar.get("component_count")
    if sidecar_count is not None and sidecar.get("present"):
        result["sidecar_component_count_matches"] = bool(sidecar_count == result["component_count"])
        if not result["sidecar_component_count_matches"]:
            errors.append("sidecar component count differs from policy component count")
    if sidecar.get("structural_pass") and not explicit_mapping:
        result["mapping_status"] = "sidecar_uses_triangle_mk_but_policy_only_declares_mkbound"
    elif explicit_mapping:
        result["mapping_status"] = "explicit"
    else:
        result["mapping_status"] = "not_available"
    result["structural_pass"] = not errors
    result["candidate_open_face_semantics_pass"] = bool(result["structural_pass"] and not review_required)
    result["formal_wall_visibility_admitted"] = bool(
        result["candidate_open_face_semantics_pass"]
        and result["explicit_mkbound_to_mk_mapping"]
        and _text(policy.get("acceptance_status")) not in {"candidate_policy_contract_only", "candidate"}
    )
    if errors:
        result["error"] = "; ".join(errors)
    return result


def _substeps_from_sources(record: Mapping[str, Any], attrs: Mapping[str, Any]) -> tuple[int | None, str | None]:
    containers: list[tuple[str, Mapping[str, Any]]] = [("material_attrs", attrs)]
    for name in ("material", "numerics", "observation", "control"):
        value = record.get(name)
        if isinstance(value, Mapping):
            containers.append((f"manifest.{name}", value))
    for source, container in containers:
        for key in SUBSTEP_KEYS:
            if key not in container:
                continue
            try:
                value = int(container[key])
            except (TypeError, ValueError):
                continue
            if value >= 1:
                return value, f"{source}.{key}"
    return None, None


def _audit_destination_spec_reference(
    record: Mapping[str, Any],
    manifest_root: Path,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    candidate: Any = None
    candidate_key = None
    for key in ("destination_spec", "transport_spec", "destination_spec_ref", "transport_spec_ref"):
        if key in record:
            candidate = record[key]
            candidate_key = key
            break
    if candidate is None and isinstance(record.get("material"), Mapping):
        material = record["material"]
        for key in ("destination_spec", "transport_spec", "destination_spec_ref", "transport_spec_ref"):
            if key in material:
                candidate = material[key]
                candidate_key = f"material.{key}"
                break
    reference = {
        "present": candidate is not None,
        "key": candidate_key,
        "path": None,
        "loaded": False,
        "error": None,
    }
    if candidate is None:
        return None, reference
    if isinstance(candidate, Mapping):
        reference["loaded"] = True
        return dict(candidate), reference
    if isinstance(candidate, str):
        try:
            path = _resolve_under(manifest_root, manifest_root, candidate)
            reference["path"] = path.name if path.parent == manifest_root else path.relative_to(manifest_root).as_posix()
            payload = json.loads(path.read_text())
            if not isinstance(payload, dict):
                raise ValueError("destination specification JSON must be an object")
            reference["loaded"] = True
            return payload, reference
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            reference["error"] = str(exc)
            return None, reference
    reference["error"] = "destination specification must be an object or release-relative JSON path"
    return None, reference


def _finite_vec(region: Mapping[str, Any], key: str) -> np.ndarray:
    if key not in region:
        raise ValueError(f"missing {key}")
    value = np.asarray(region[key], dtype=float)
    if value.shape != (3,) or not np.all(np.isfinite(value)):
        raise ValueError(f"{key} must be a finite length-3 vector")
    return value


def _validate_region(region: Any, role: str) -> None:
    if not isinstance(region, Mapping):
        raise ValueError(f"{role} must be an object")
    if not isinstance(region.get("name"), str) or not region["name"].strip():
        raise ValueError(f"{role}.name must be non-empty")
    kind = region.get("type")
    if kind not in {"aabb", "halfspace", "sphere"}:
        raise ValueError(f"{role}.type is unsupported")
    if kind == "aabb":
        lower = _finite_vec(region, "min")
        upper = _finite_vec(region, "max")
        if np.any(upper < lower):
            raise ValueError(f"{role}.max is below min")
    elif kind == "halfspace":
        normal = _finite_vec(region, "normal")
        if np.linalg.norm(normal) <= 0.0:
            raise ValueError(f"{role}.normal is zero")
        offset = _finite_float(region.get("offset"))
        if offset is None or region.get("side") not in {"le", "ge"}:
            raise ValueError(f"{role} needs finite offset and explicit side")
    else:
        _finite_vec(region, "center")
        radius = _finite_float(region.get("radius"))
        if radius is None or radius <= 0.0:
            raise ValueError(f"{role}.radius must be positive")


def _validate_transport_spec(spec: Mapping[str, Any]) -> None:
    if spec.get("lifecycle_model") not in {"closed", "open"}:
        raise ValueError("lifecycle_model must be explicitly closed or open")
    frame = spec.get("destination_frame")
    if not isinstance(frame, Mapping) or frame.get("kind") not in {"world", "moving_affine"}:
        raise ValueError("destination_frame must be world or moving_affine")
    if frame.get("kind") == "moving_affine" and not isinstance(frame.get("world_from_frame_dataset"), str):
        raise ValueError("moving_affine destination_frame needs a dataset")
    sources = spec.get("sources", {"mode": "mk"})
    if not isinstance(sources, Mapping) or sources.get("mode", "mk") not in {"mk", "regions"}:
        raise ValueError("sources.mode must be mk or regions")
    if sources.get("mode", "mk") == "regions":
        regions = sources.get("regions")
        if not isinstance(regions, list) or not regions:
            raise ValueError("sources.regions must be non-empty")
        for index, region in enumerate(regions):
            _validate_region(region, f"sources.regions[{index}]")
    destinations = spec.get("destinations")
    if not isinstance(destinations, list) or not destinations:
        raise ValueError("destinations must be non-empty")
    names = []
    for index, region in enumerate(destinations):
        _validate_region(region, f"destinations[{index}]")
        names.append(region["name"])
    if len(names) != len(set(names)):
        raise ValueError("destination names must be unique")


def _points_in_region(points: np.ndarray, region: Mapping[str, Any]) -> np.ndarray:
    kind = region["type"]
    if kind == "aabb":
        lower = np.asarray(region["min"], dtype=float)
        upper = np.asarray(region["max"], dtype=float)
        return np.all((points >= lower) & (points <= upper), axis=1)
    if kind == "halfspace":
        normal = np.asarray(region["normal"], dtype=float)
        signed = points @ normal - float(region["offset"])
        return signed <= 0.0 if region["side"] == "le" else signed >= 0.0
    center = np.asarray(region["center"], dtype=float)
    return np.linalg.norm(points - center, axis=1) <= float(region["radius"])


def _frame_points(
    h5: h5py.File,
    points: np.ndarray,
    frame_index: int,
    frame_spec: Mapping[str, Any],
) -> np.ndarray:
    if frame_spec.get("kind") == "world":
        return np.asarray(points, dtype=float)
    dataset = frame_spec.get("world_from_frame_dataset")
    if not isinstance(dataset, str) or dataset not in h5:
        raise ValueError(f"moving frame transform dataset unavailable: {dataset!r}")
    transforms = np.asarray(h5[dataset][:], dtype=float)
    if transforms.ndim != 3 or transforms.shape[1:] != (4, 4) or not np.all(np.isfinite(transforms)):
        raise ValueError("moving frame transforms must have shape [T,4,4] and finite values")
    transform = transforms[int(frame_index)]
    if not np.allclose(transform[3], [0.0, 0.0, 0.0, 1.0], atol=1e-8, rtol=0.0):
        raise ValueError("moving frame transform is not homogeneous")
    inverse = np.linalg.inv(transform)
    homogeneous = np.column_stack((np.asarray(points, dtype=float), np.ones(len(points))))
    return (homogeneous @ inverse.T)[:, :3]


def _audit_source_destination(
    spec: Mapping[str, Any] | None,
    reference: Mapping[str, Any],
    h5: h5py.File,
    material_position: np.ndarray | None,
    material_valid: np.ndarray | None,
    material_weight: np.ndarray | None,
    material_source: np.ndarray | None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "blocked_no_destination_spec" if spec is None and not reference.get("error") else "failed",
        "destination_spec": dict(reference),
        "lifecycle_model": spec.get("lifecycle_model") if spec is not None else None,
        "required_categories": ["destinations", "in_domain_unclassified", "numerical_loss"],
        "loss_category_used": None,
        "legacy_x_bins_used": False,
        "source_partition_overlap_count": None,
        "per_source": {},
        "closure_pass": False,
        "error": reference.get("error"),
    }
    if spec is None:
        return result
    try:
        _validate_transport_spec(spec)
        if material_position is None or material_valid is None or material_weight is None or material_source is None:
            raise ValueError("material trajectory is required for tracer source-destination closure")
        sources_spec = spec.get("sources", {"mode": "mk"})
        source_masks: dict[str, np.ndarray] = {}
        if sources_spec.get("mode", "mk") == "mk":
            for source in sorted(int(value) for value in np.unique(material_source)):
                source_masks[str(source)] = material_source == source
        else:
            initial_points = _frame_points(
                h5,
                np.asarray(material_position[0], dtype=float),
                0,
                sources_spec.get("frame", {"kind": "world"}),
            )
            for region in sources_spec["regions"]:
                source_masks[region["name"]] = _points_in_region(initial_points, region)
        source_union = np.zeros(len(material_source), dtype=bool)
        source_overlap = np.zeros(len(material_source), dtype=bool)
        for mask in source_masks.values():
            source_overlap |= source_union & mask
            source_union |= mask
        result["source_partition_overlap_count"] = int(source_overlap.sum())
        final_points = _frame_points(
            h5,
            np.asarray(material_position[-1], dtype=float),
            len(h5["time"]) - 1,
            spec["destination_frame"],
        )
        final_valid = np.asarray(material_valid[-1], dtype=bool)
        weights = np.asarray(material_weight, dtype=float)
        loss_name = "numerical_loss" if spec["lifecycle_model"] == "closed" else "unknown_exit"
        result["loss_category_used"] = loss_name
        for source_name, source_mask in source_masks.items():
            denominator = float(np.sum(weights[source_mask], dtype=np.float64))
            remaining = source_mask & final_valid
            mass_kg: dict[str, float] = {}
            overlap_count = 0
            for region in spec["destinations"]:
                selected = source_mask & final_valid & _points_in_region(final_points, region)
                overlap_count += int(np.sum(selected & ~remaining))
                assigned = selected & remaining
                mass_kg[region["name"]] = float(np.sum(weights[assigned], dtype=np.float64))
                remaining &= ~selected
            mass_kg["in_domain_unclassified"] = float(np.sum(weights[remaining], dtype=np.float64))
            failed = source_mask & ~final_valid
            mass_kg[loss_name] = float(np.sum(weights[failed], dtype=np.float64))
            accounted = float(sum(mass_kg.values()))
            fractions = {name: value / max(denominator, 1e-30) for name, value in mass_kg.items()}
            result["per_source"][str(source_name)] = {
                "initial_mass_kg": denominator,
                "mass_kg": mass_kg,
                "mass_fraction": fractions,
                "destination_overlap_count": overlap_count,
                "closure_error_kg": accounted - denominator,
                "closure_pass": bool(_close(accounted, denominator) and overlap_count == 0),
            }
        result["status"] = "pass" if result["per_source"] and all(
            row["closure_pass"] for row in result["per_source"].values()
        ) and result["source_partition_overlap_count"] == 0 else "failed"
        result["closure_pass"] = result["status"] == "pass"
    except (ValueError, KeyError, np.linalg.LinAlgError) as exc:
        result["status"] = "failed"
        result["error"] = str(exc)
    return result


def _audit_case(
    manifest_path: Path,
    record: Mapping[str, Any],
    policy: Mapping[str, Any] | None,
    policy_path: Path | None,
) -> dict[str, Any]:
    manifest_root = manifest_path.parent
    case_id = _text(record.get("case_id", record.get("id", "unknown")))
    hdf5_ref = record.get("hdf5")
    case_result: dict[str, Any] = {
        "case_id": case_id,
        "family": record.get("family"),
        "split": record.get("split"),
        "lineage_group_id": record.get("lineage_group_id"),
        "hdf5": hdf5_ref,
        "artifact": {"path": hdf5_ref, "sha256": None, "present": False},
        "trajectory": {
            "status": "failed",
            "missing_root_attrs": list(REQUIRED_ROOT_ATTRS),
            "missing_datasets": list(REQUIRED_TRAJECTORY_DATASETS),
        },
        "seed_material": {"status": "blocked_missing_trajectory", "material_present": False},
        "mass_weights": {"status": "blocked_missing_material"},
        "cadence_and_integration": {"status": "blocked_missing_trajectory"},
        "support_failure": {"status": "blocked_missing_material"},
        "wall_open_face": {
            "status": "blocked_missing_trajectory",
            "sidecar": {"present": False, "structural_pass": False, "error": "not_audited"},
            "policy": {"policy_present": False, "structural_pass": False, "error": "not_audited"},
        },
        "source_destination": {
            "status": "blocked_missing_trajectory",
            "closure_pass": False,
            "required_categories": ["destinations", "in_domain_unclassified", "numerical_loss"],
        },
        "acceptance": "candidate_only_rejected",
    }
    if not isinstance(hdf5_ref, str):
        case_result["artifact"]["error"] = "manifest hdf5 reference missing"
        return case_result
    try:
        h5_path = _resolve_under(manifest_root, manifest_root, hdf5_ref)
    except ValueError as exc:
        case_result["artifact"]["error"] = str(exc)
        return case_result
    case_result["artifact"] = {
        "path": hdf5_ref,
        "sha256": _sha256(h5_path),
        "present": h5_path.is_file(),
    }
    if not h5_path.is_file():
        case_result["artifact"]["error"] = "hdf5_missing"
        return case_result

    material_position = material_valid = material_weight = material_source = None
    with h5py.File(h5_path, "r") as h5:
        missing_attrs = [name for name in REQUIRED_ROOT_ATTRS if name not in h5.attrs]
        missing_datasets = [name for name in REQUIRED_TRAJECTORY_DATASETS if name not in h5]
        trajectory = {
            "status": "failed",
            "missing_root_attrs": missing_attrs,
            "missing_datasets": missing_datasets,
            "root_attrs_present": len(missing_attrs) == 0,
            "datasets_present": len(missing_datasets) == 0,
            "time_strictly_increasing": False,
            "finite_when_valid": False,
            "identity_unique": False,
            "initial_fluid_count": 0,
            "initial_fluid_mass_kg": None,
            "frames": None,
            "identity_slots": None,
            "introduced_after_initial": None,
            "missing_at_final": None,
            "closed_identity_lifecycle_observed": None,
        }
        arrays: dict[str, np.ndarray] = {}
        if not missing_datasets:
            arrays = {name: np.asarray(h5[name][:]) for name in REQUIRED_TRAJECTORY_DATASETS}
            time = np.asarray(arrays["time"], dtype=float)
            valid = np.asarray(arrays["valid"], dtype=bool)
            shape_ok = bool(
                valid.ndim == 2
                and arrays["position"].shape == (valid.shape[0], valid.shape[1], 3)
                and arrays["velocity"].shape == arrays["position"].shape
                and all(arrays[name].shape == valid.shape for name in ("density", "pressure", "mass", "type", "mk"))
                and arrays["particle_id"].shape == (valid.shape[1],)
                and arrays["particle_zone"].shape == (valid.shape[1],)
            )
            trajectory["shape_compatible"] = shape_ok
            trajectory["time_strictly_increasing"] = _strict_time(time)
            if shape_ok:
                finite_fields = []
                for name in ("position", "velocity", "density", "pressure", "mass"):
                    values = np.asarray(arrays[name])
                    finite_fields.append(bool(np.all(np.isfinite(values[valid]))))
                trajectory["finite_when_valid"] = bool(all(finite_fields))
                keys = np.column_stack((arrays["particle_zone"].astype(np.int64), arrays["particle_id"].astype(np.int64)))
                trajectory["identity_unique"] = bool(len(np.unique(keys, axis=0)) == len(keys))
                initial_fluid = valid[0] & (arrays["type"][0] == 3)
                trajectory["initial_fluid_count"] = int(initial_fluid.sum())
                trajectory["initial_fluid_mass_kg"] = float(np.sum(arrays["mass"][0, initial_fluid], dtype=np.float64))
                trajectory["frames"] = int(valid.shape[0])
                trajectory["identity_slots"] = int(valid.shape[1])
                trajectory["introduced_after_initial"] = int(np.sum(~valid[0] & np.any(valid, axis=0)))
                trajectory["missing_at_final"] = int(np.sum(valid[0] & ~valid[-1]))
                trajectory["closed_identity_lifecycle_observed"] = bool(
                    not np.any(valid[:, ~valid[0]]) and np.all(valid[:, valid[0]])
                )
                trajectory["status"] = "pass" if all(
                    (trajectory.get(key, False) is True) for key in (
                        "root_attrs_present", "datasets_present", "shape_compatible",
                        "time_strictly_increasing", "finite_when_valid", "identity_unique",
                    )
                ) else "failed"
        else:
            trajectory["shape_compatible"] = False
        case_result["trajectory"] = trajectory

        if trajectory["status"] == "pass":
            valid = np.asarray(arrays["valid"], dtype=bool)
            position = np.asarray(arrays["position"], dtype=float)
            mass = np.asarray(arrays["mass"], dtype=float)
            particle_type = np.asarray(arrays["type"])
            particle_mk = np.asarray(arrays["mk"])
            time = np.asarray(arrays["time"], dtype=float)
            initial_fluid = valid[0] & (particle_type[0] == 3)
            identity_map = {
                (int(zone), int(pid)): index
                for index, (zone, pid) in enumerate(zip(arrays["particle_zone"], arrays["particle_id"]))
            }

            material_group = h5.get("material")
            if material_group is None:
                case_result["seed_material"] = {
                    "status": "failed",
                    "material_present": False,
                    "missing_datasets": list(REQUIRED_MATERIAL_DATASETS),
                    "matching_method": "compound_key_(particle_zone,particle_id)",
                    "source_semantics": "not_available",
                }
                case_result["mass_weights"] = {"status": "blocked_missing_material"}
                case_result["support_failure"] = {"status": "blocked_missing_material"}
            else:
                missing_material = [name for name in REQUIRED_MATERIAL_DATASETS if name not in material_group]
                material_result: dict[str, Any] = {
                    "status": "failed",
                    "material_present": True,
                    "missing_datasets": missing_material,
                    "matching_method": "compound_key_(particle_zone,particle_id)",
                    "tracer_count": 0,
                    "tracer_id_unique": False,
                    "seed_key_unique": False,
                    "seed_keys_resolve": False,
                    "seed_is_initial_fluid": False,
                    "source_label_matches_initial_mk": False,
                    "initial_position_matches_seed": False,
                    "valid_shape": False,
                    "validity_monotone": False,
                    "finite_position_when_valid": False,
                    "seed_selection": _text(material_group.attrs.get("seed_selection"), ""),
                    "source_label_semantics": _text(material_group.attrs.get("source_label_semantics"), "missing"),
                    "source_semantics": "initial_solver_mk_proxy",
                    "provenance_warning": None,
                }
                if not missing_material:
                    material_tracer_id = np.asarray(material_group["tracer_id"][:])
                    seed_id = np.asarray(material_group["seed_particle_id"][:])
                    seed_zone = np.asarray(material_group["seed_particle_zone"][:])
                    material_source = np.asarray(material_group["source_label"][:])
                    material_weight = np.asarray(material_group["mass_weight"][:], dtype=float)
                    material_valid = np.asarray(material_group["valid"][:], dtype=bool)
                    material_position = np.asarray(material_group["position"][:], dtype=float)
                    k = len(material_tracer_id)
                    material_result["tracer_count"] = int(k)
                    material_result["tracer_id_unique"] = bool(len(np.unique(material_tracer_id)) == k)
                    material_result["seed_key_unique"] = bool(len(set(zip(seed_zone.tolist(), seed_id.tolist()))) == k)
                    material_result["valid_shape"] = bool(material_valid.shape == (len(time), k))
                    material_result["position_shape"] = bool(material_position.shape == (len(time), k, 3))
                    if material_result["valid_shape"] and material_result["position_shape"]:
                        material_result["validity_monotone"] = bool(
                            not np.any(material_valid[1:] & ~material_valid[:-1])
                        )
                        material_result["finite_position_when_valid"] = bool(
                            np.all(np.isfinite(material_position[material_valid]))
                        )
                    seed_indices = []
                    resolvable = True
                    for zone, pid in zip(seed_zone, seed_id):
                        index = identity_map.get((int(zone), int(pid)))
                        if index is None:
                            resolvable = False
                            break
                        seed_indices.append(index)
                    material_result["seed_keys_resolve"] = resolvable
                    if resolvable and seed_indices:
                        seed_indices_array = np.asarray(seed_indices, dtype=int)
                        seed_fluid = initial_fluid[seed_indices_array]
                        material_result["seed_is_initial_fluid"] = bool(np.all(seed_fluid))
                        actual_source = particle_mk[0, seed_indices_array]
                        material_result["source_label_matches_initial_mk"] = bool(np.array_equal(material_source, actual_source))
                        if material_position.shape == (len(time), k, 3):
                            material_result["initial_position_matches_seed"] = bool(
                                np.allclose(material_position[0], position[0, seed_indices_array], rtol=0.0, atol=1e-7)
                            )
                    required_seed_checks = (
                        "tracer_id_unique", "seed_key_unique", "seed_keys_resolve",
                        "seed_is_initial_fluid", "source_label_matches_initial_mk",
                        "initial_position_matches_seed", "valid_shape", "position_shape",
                        "validity_monotone", "finite_position_when_valid",
                    )
                    material_result["status"] = "pass" if all(material_result.get(key, False) for key in required_seed_checks) else "failed"
                    if not material_result["seed_selection"]:
                        material_result["provenance_warning"] = "material.attrs.seed_selection_missing"
                    elif material_result["source_label_semantics"] == "missing":
                        material_result["provenance_warning"] = "material.attrs.source_label_semantics_missing"
                case_result["seed_material"] = material_result

                if material_weight is not None and material_source is not None:
                    weight_finite_nonnegative = bool(np.all(np.isfinite(material_weight)) and np.all(material_weight >= 0.0))
                    total_weight = float(np.sum(material_weight, dtype=np.float64))
                    initial_mass = float(np.sum(mass[0, initial_fluid], dtype=np.float64))
                    source_values = sorted(set(int(value) for value in np.unique(material_source)))
                    initial_by_source = {
                        str(source): float(np.sum(mass[0, initial_fluid & (particle_mk[0] == source)], dtype=np.float64))
                        for source in sorted(set(source_values) | set(int(value) for value in np.unique(particle_mk[0, initial_fluid])))
                    }
                    represented_by_source = {
                        str(source): float(np.sum(material_weight[material_source == int(source)], dtype=np.float64))
                        for source in sorted(
                            {str(source) for source in source_values} | set(initial_by_source),
                            key=int,
                        )
                    }
                    per_source = {}
                    all_source_names = sorted(
                        {str(source) for source in source_values} | set(initial_by_source),
                        key=int,
                    )
                    for source in all_source_names:
                        expected = initial_by_source.get(source, 0.0)
                        represented = represented_by_source.get(source, 0.0)
                        per_source[source] = {
                            "initial_fluid_mass_kg": expected,
                            "represented_mass_weight_kg": represented,
                            "closure_error_kg": represented - expected,
                            "pass": bool(_close(represented, expected)),
                        }
                    mass_result = {
                        "status": "pass" if weight_finite_nonnegative and _close(total_weight, initial_mass) and all(row["pass"] for row in per_source.values()) else "failed",
                        "finite_nonnegative": weight_finite_nonnegative,
                        "weight_vector_shape": list(material_weight.shape),
                        "represented_initial_mass_kg": total_weight,
                        "initial_fluid_mass_kg": initial_mass,
                        "closure_error_kg": total_weight - initial_mass,
                        "per_source": per_source,
                        "renormalized_to_survivors": False,
                        "denominator_semantics": "initial represented material mass; failed mass is not renormalized",
                    }
                    case_result["mass_weights"] = mass_result
                else:
                    case_result["mass_weights"] = {"status": "failed", "error": "material mass_weight/source_label unavailable"}

            attrs = {str(key): value for key, value in h5.attrs.items()}
            declared_cadence = _finite_float((record.get("observation") or {}).get("frame_interval_s")) if isinstance(record.get("observation"), Mapping) else None
            observed_cadence = float(np.median(np.diff(time)))
            material_time_aligned = bool(
                material_position is None or material_position.shape[0] == len(time)
            )
            substeps, substeps_source = _substeps_from_sources(record, attrs if material_group is None else dict(material_group.attrs))
            dp = _finite_float((record.get("numerics") or {}).get("particle_spacing_m")) if isinstance(record.get("numerics"), Mapping) else None
            cadence_result = {
                "output_cadence_status": "pass" if declared_cadence is not None and _close(declared_cadence, observed_cadence) and material_time_aligned else "failed",
                "declared_saved_cadence_s": declared_cadence,
                "observed_saved_cadence_median_s": observed_cadence,
                "observed_saved_cadence_min_s": float(np.min(np.diff(time))),
                "observed_saved_cadence_max_s": float(np.max(np.diff(time))),
                "declared_matches_observed": bool(declared_cadence is not None and _close(declared_cadence, observed_cadence)),
                "material_time_axis_aligned": material_time_aligned,
                "integration_method": _text(material_group.attrs.get("integration"), "missing") if material_group is not None else "not_available",
                "substeps_per_saved_interval": substeps,
                "substeps_explicit_in_artifact_or_manifest": substeps is not None,
                "substeps_source": substeps_source,
                "inferred_code_default_substeps": 1,
                "substep_dt_median_s": float(observed_cadence / substeps) if substeps is not None else None,
                "cadence_and_substeps_are_separate_contracts": True,
                "status": "pass" if declared_cadence is not None and _close(declared_cadence, observed_cadence) and material_time_aligned and substeps is not None else "failed_missing_or_mismatched_contract",
                "provenance_warning": None if substeps is not None else "saved output cadence is present, but integration substeps were not persisted",
            }
            case_result["cadence_and_integration"] = cadence_result

            if material_group is not None and material_valid is not None and material_weight is not None and material_source is not None:
                support_present = [name for name in SUPPORT_DATASETS if name in material_group]
                support_missing = [name for name in SUPPORT_DATASETS if name not in material_group]
                support_arrays: dict[str, np.ndarray] = {}
                for name in support_present:
                    values = np.asarray(material_group[name][:])
                    if values.shape == material_valid.shape:
                        support_arrays[name] = values
                terminal_failed = ~material_valid[-1]
                threshold = 1.75 * dp if dp is not None and dp > 0.0 else None
                distance_exceedance = np.zeros(len(material_weight), dtype=bool)
                if "nearest_support_distance" in support_arrays and threshold is not None:
                    distance_values = np.asarray(support_arrays["nearest_support_distance"], dtype=float)
                    distance_exceedance = np.any(np.isfinite(distance_values) & (distance_values > threshold), axis=0)
                gate_failure = np.zeros(len(material_weight), dtype=bool)
                if "support_gate_pass" in support_arrays:
                    gate_failure = np.any(~np.asarray(support_arrays["support_gate_pass"], dtype=bool)[1:], axis=0)
                wall_crossing = np.zeros(len(material_weight), dtype=bool)
                if "wall_crossing" in support_arrays:
                    wall_crossing = np.any(np.asarray(support_arrays["wall_crossing"], dtype=bool), axis=0)
                reasons = np.full(len(material_weight), "none", dtype=object)
                reasons[terminal_failed & wall_crossing] = "wall_crossing"
                reasons[terminal_failed & ~wall_crossing & gate_failure] = "support_gate"
                reasons[terminal_failed & ~wall_crossing & ~gate_failure & distance_exceedance] = "support_distance_exceedance"
                reasons[terminal_failed & (reasons == "none")] = "unattributed_failure"
                reason_values = sorted(set(str(value) for value in reasons[terminal_failed]))
                failed_mass_by_reason = {
                    reason: {
                        "tracer_count": int(np.sum(terminal_failed & (reasons == reason))),
                        "mass_kg": float(np.sum(material_weight[terminal_failed & (reasons == reason)], dtype=np.float64)),
                    }
                    for reason in reason_values
                }
                failed_mass_by_source_and_reason = {}
                for source in sorted(int(value) for value in np.unique(material_source)):
                    source_failed = terminal_failed & (material_source == source)
                    failed_mass_by_source_and_reason[str(source)] = {
                        reason: {
                            "tracer_count": int(np.sum(source_failed & (reasons == reason))),
                            "mass_kg": float(np.sum(material_weight[source_failed & (reasons == reason)], dtype=np.float64)),
                        }
                        for reason in sorted(set(str(value) for value in reasons[source_failed]))
                    }
                failed_mass = float(np.sum(material_weight[terminal_failed], dtype=np.float64))
                represented_mass = float(np.sum(material_weight, dtype=np.float64))
                if not terminal_failed.any():
                    support_status = "not_auditable_missing_reason_channel" if support_missing else "pass_no_terminal_failure"
                elif "support_gate_pass" not in support_arrays:
                    support_status = "partial_distance_only" if np.all(distance_exceedance[terminal_failed]) else "not_auditable_missing_support_gate"
                else:
                    support_status = "pass" if all(reason != "unattributed_failure" for reason in reasons[terminal_failed]) else "partial"
                case_result["support_failure"] = {
                    "status": support_status,
                    "terminal_failed_tracer_count": int(terminal_failed.sum()),
                    "terminal_failed_mass_kg": failed_mass,
                    "terminal_failed_mass_fraction": failed_mass / max(represented_mass, 1e-30),
                    "failed_mass_by_source": _mass_rows(material_weight, material_source, terminal_failed),
                    "failed_mass_by_reason": failed_mass_by_reason,
                    "failed_mass_by_source_and_reason": failed_mass_by_source_and_reason,
                    "reason_assignment_is_exclusive": True,
                    "support_datasets_present": support_present,
                    "support_datasets_missing": support_missing,
                    "support_history_shape_match": {name: bool(name in support_arrays) for name in support_present},
                    "support_distance_threshold_m": threshold,
                    "support_distance_threshold_source": "W11 default maximum_support_distance = 1.75 * dp",
                    "failed_tracers_with_distance_exceedance": int(np.sum(terminal_failed & distance_exceedance)),
                    "failed_tracers_with_explicit_gate_failure": int(np.sum(terminal_failed & gate_failure)),
                    "failed_tracers_with_wall_crossing": int(np.sum(terminal_failed & wall_crossing)),
                    "failed_mass_source_closure_error_kg": float(
                        sum(row["mass_kg"] for row in _mass_rows(material_weight, material_source, terminal_failed).values()) - failed_mass
                    ),
                }
            else:
                case_result["support_failure"] = {"status": "blocked_missing_material"}

            sidecar_ref = (record.get("geometry") or {}).get("boundary_sidecar") if isinstance(record.get("geometry"), Mapping) else None
            try:
                sidecar_path = _resolve_under(manifest_root, manifest_root, sidecar_ref) if sidecar_ref is not None else None
            except ValueError as exc:
                sidecar_path = None
                sidecar_error = str(exc)
            else:
                sidecar_error = None
            sidecar_result = _audit_sidecar(sidecar_path, time, case_id, manifest_root)
            if sidecar_error:
                sidecar_result["error"] = sidecar_error
                sidecar_result["structural_pass"] = False
            policy_result = _audit_boundary_policy(policy, case_id, sidecar_result)
            material_attrs = dict(material_group.attrs) if material_group is not None else {}
            wall_value = _text(material_attrs.get("wall_visibility"), "").strip().lower()
            wall_used = wall_value in {"true", "1", "yes", "enabled", "sidecar_world_triangles", "wall_aware"}
            wall_status = "formal_pass" if (
                sidecar_result["structural_pass"]
                and policy_result["formal_wall_visibility_admitted"]
                and wall_used
            ) else (
                "candidate_sidecar_policy_only" if sidecar_result["structural_pass"] and policy_result["structural_pass"] else "blocked_missing_wall_contract"
            )
            case_result["wall_open_face"] = {
                "status": wall_status,
                "linked_sidecar": sidecar_ref,
                "material_wall_visibility_attr": _text(material_attrs.get("wall_visibility"), "missing"),
                "material_wall_visibility_used": wall_used,
                "sidecar": sidecar_result,
                "policy": policy_result,
                "policy_path": _relative(policy_path, manifest_root) if policy_path is not None else None,
                "finite_sidecar_is_not_material_wall_awareness": bool(sidecar_result["structural_pass"] and not wall_used),
            }

            spec, spec_reference = _audit_destination_spec_reference(record, manifest_root)
            case_result["source_destination"] = _audit_source_destination(
                spec,
                spec_reference,
                h5,
                material_position,
                material_valid,
                material_weight,
                material_source,
            )
        else:
            # Keep the missing/invalid trajectory case explicit and avoid
            # guessing source, cadence, wall, or destination semantics.
            case_result["artifact"]["error"] = "trajectory_contract_failed"
    return case_result


def cross_resolution_permutation_probe() -> dict[str, Any]:
    """Prove that array-position matching is not an invariant across resolution.

    The two rows represent the same source/destination mass table with a
    different storage order.  Aggregate source×destination mass is invariant;
    naive row-by-row comparison is not.  This is a deterministic contract
    probe, not a physical scenario.
    """
    source = np.asarray([1, 1, 2, 2], dtype=np.int64)
    destination = np.asarray(["left", "right", "left", "right"], dtype=object)
    weight = np.asarray([1.0, 3.0, 2.0, 4.0], dtype=float)
    permutation = np.asarray([2, 0, 3, 1], dtype=int)

    def aggregate(sources: np.ndarray, destinations: np.ndarray, weights: np.ndarray) -> dict[str, float]:
        return {
            f"{int(s)}:{str(d)}": float(np.sum(weights[(sources == s) & (destinations == d)], dtype=np.float64))
            for s in sorted(set(int(value) for value in sources))
            for d in sorted(set(str(value) for value in destinations))
            if np.any((sources == s) & (destinations == d))
        }

    permuted_source = source[permutation]
    permuted_destination = destination[permutation]
    permuted_weight = weight[permutation]
    naive_mismatch = int(np.sum((source != permuted_source) | (destination != permuted_destination)))
    first = aggregate(source, destination, weight)
    second = aggregate(permuted_source, permuted_destination, permuted_weight)
    return {
        "array_index_matching_allowed": False,
        "comparison_mode": "source_destination_mass_aggregate_only",
        "rowwise_match_key": "none unless an explicit stable material key is declared",
        "permutation": permutation.tolist(),
        "naive_array_index_mismatch_count": naive_mismatch,
        "aggregate_source_destination_mass_original_kg": first,
        "aggregate_source_destination_mass_permuted_kg": second,
        "aggregate_invariant_under_permutation": bool(first == second),
        "negative_control_detects_index_matching": bool(naive_mismatch > 0 and first == second),
        "interpretation": "跨分辨率不得用 particle/material array index 对齐；应比较质量聚合、分布或显式稳定 key。",
    }


def _cross_resolution_audit(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    records = list(records)
    groups: dict[str, list[str]] = {}
    for record in records:
        group = record.get("resolution_group_id") or record.get("resolution_group")
        if isinstance(group, str) and group.strip():
            groups.setdefault(group, []).append(_text(record.get("case_id", record.get("id", "unknown"))))
    explicit_pairs = {name: sorted(case_ids) for name, case_ids in groups.items() if len(case_ids) > 1}
    return {
        "array_index_matching_allowed": False,
        "explicit_resolution_groups": {name: sorted(case_ids) for name, case_ids in groups.items()},
        "explicit_cross_resolution_pairs": explicit_pairs,
        "cross_resolution_pair_count": len(explicit_pairs),
        "actual_release_rowwise_comparisons_performed": 0,
        "actual_release_comparison_status": "no_explicit_resolution_pairs" if not explicit_pairs else "aggregate_only_required",
        "permutation_negative_control": cross_resolution_permutation_probe(),
        "rule": "rowwise array matching is forbidden; use source×destination mass aggregates or an explicitly declared stable material key",
    }


def _load_policy(manifest: Mapping[str, Any], manifest_path: Path) -> tuple[dict[str, Any] | None, Path | None, str | None]:
    reference = manifest.get("boundary_policy")
    if reference is None:
        return None, None, "manifest_boundary_policy_link_missing"
    try:
        path = _resolve_under(manifest_path.parent, manifest_path.parent, reference)
        if not path.is_file():
            return None, path, "boundary_component_policy_file_missing"
        payload = json.loads(path.read_text())
        if not isinstance(payload, dict):
            return None, path, "boundary_component_policy_must_be_object"
        return payload, path, None
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return None, None, str(exc)


def build_report(
    manifest_path: Path = DEFAULT_MANIFEST,
    *,
    lab_root: Path | None = None,
) -> dict[str, Any]:
    """Build a deterministic actual-scenario contract report."""
    manifest_path = Path(manifest_path).resolve()
    if lab_root is None:
        lab_root = LAB
    lab_root = Path(lab_root).resolve()
    manifest = json.loads(manifest_path.read_text())
    if not isinstance(manifest, dict) or not isinstance(manifest.get("cases"), list):
        raise ValueError("manifest must contain a cases list")
    policy, policy_path, policy_error = _load_policy(manifest, manifest_path)
    cases = [_audit_case(manifest_path, record, policy, policy_path) for record in manifest["cases"]]
    material_cases = [case for case in cases if case["seed_material"].get("material_present")]
    failed_mass_by_case_source = {
        case["case_id"]: case["support_failure"].get("failed_mass_by_source", {})
        for case in cases
        if case["support_failure"].get("failed_mass_by_source") is not None
    }
    total_represented = float(sum(
        case["mass_weights"].get("represented_initial_mass_kg", 0.0) or 0.0
        for case in cases
    ))
    total_failed = float(sum(
        case["support_failure"].get("terminal_failed_mass_kg", 0.0) or 0.0
        for case in cases
    ))
    summary = {
        "case_count": len(cases),
        "material_present_count": len(material_cases),
        "seed_material_contract_pass_count": sum(case["seed_material"].get("status") == "pass" for case in cases),
        "source_semantics_declared_count": sum(
            case["seed_material"].get("source_label_semantics") not in {None, "", "missing"}
            for case in cases
        ),
        "mass_weight_closure_pass_count": sum(case["mass_weights"].get("status") == "pass" for case in cases),
        "output_cadence_pass_count": sum(case["cadence_and_integration"].get("output_cadence_status") == "pass" for case in cases),
        "explicit_substeps_count": sum(case["cadence_and_integration"].get("substeps_explicit_in_artifact_or_manifest", False) for case in cases),
        "support_diagnostic_complete_count": sum(
            case["support_failure"].get("status") in {"pass", "partial"} and not case["support_failure"].get("support_datasets_missing")
            for case in cases
        ),
        "support_failure_auditable_count": sum(
            case["support_failure"].get("status") in {"pass", "partial", "partial_distance_only"}
            for case in cases
        ),
        "sidecar_structural_pass_count": sum(case["wall_open_face"].get("sidecar", {}).get("structural_pass", False) for case in cases),
        "open_face_policy_structural_pass_count": sum(case["wall_open_face"].get("policy", {}).get("structural_pass", False) for case in cases),
        "candidate_open_face_semantics_pass_count": sum(case["wall_open_face"].get("policy", {}).get("candidate_open_face_semantics_pass", False) for case in cases),
        "open_face_review_required_count": sum(case["wall_open_face"].get("policy", {}).get("review_required", False) for case in cases),
        "material_wall_visibility_used_count": sum(case["wall_open_face"].get("material_wall_visibility_used", False) for case in cases),
        "formal_wall_visibility_admission_count": sum(case["wall_open_face"].get("policy", {}).get("formal_wall_visibility_admitted", False) for case in cases),
        "destination_spec_present_count": sum(case["source_destination"].get("destination_spec", {}).get("present", False) for case in cases),
        "source_destination_closure_pass_count": sum(case["source_destination"].get("closure_pass", False) for case in cases),
        "represented_initial_mass_kg": total_represented,
        "failed_mass_kg": total_failed,
        "failed_mass_fraction_of_represented": total_failed / max(total_represented, 1e-30),
        "failed_mass_by_case_source": failed_mass_by_case_source,
        "legacy_x_destination_proxy_used_count": sum(case["source_destination"].get("legacy_x_bins_used", False) for case in cases),
        "formal_material_target_count": 0,
    }
    inventory = _static_inventory(lab_root)
    open_gaps = list(inventory["open_interface_gaps"])
    if summary["explicit_substeps_count"] < summary["material_present_count"]:
        open_gaps.append({
            "id": "actual_release_substep_provenance_missing",
            "severity": "P1",
            "evidence": "release material groups: integration=Heun but no substeps_per_saved_interval",
            "finding": f"{summary['material_present_count'] - summary['explicit_substeps_count']}/{summary['material_present_count']} 个 material artifact 没有显式积分子步 provenance。",
            "minimum_interface": "重做 materialization 时把输出 cadence、积分子步和子步 dt 一起写入 artifact/manifest。",
        })
    if summary["material_wall_visibility_used_count"] < summary["material_present_count"]:
        open_gaps.append({
            "id": "actual_release_wall_visibility_not_used",
            "severity": "P1",
            "evidence": "material.attrs.wall_visibility and linked sidecars",
            "finding": f"{summary['material_present_count'] - summary['material_wall_visibility_used_count']}/{summary['material_present_count']} 个 material artifact 没有声明使用 wall-aware visibility。",
            "minimum_interface": "用 sidecar + open-face policy 重新生成或重算 tracer；sidecar 存在本身不追溯修改旧轨迹。",
        })
    if summary["destination_spec_present_count"] == 0:
        open_gaps.append({
            "id": "actual_release_destination_spec_missing",
            "severity": "P1",
            "evidence": "release manifest cases[].destination_spec and material.destination_spec",
            "finding": "当前 release 没有任何可执行 destination specification，因此 source-destination closure 不能被正式计算。",
            "minimum_interface": "为一个真实案例先冻结 source、destination_frame、destinations、in_domain_unclassified、numerical_loss/exit reason。",
        })
    if summary["support_diagnostic_complete_count"] < summary["material_present_count"]:
        open_gaps.append({
            "id": "actual_release_support_reason_channel_missing",
            "severity": "P1",
            "evidence": "material datasets under release/v0.1-development/data/*/material",
            "finding": "当前 material 只保留 nearest_support_distance，缺少 support_gate_pass/ESS/geometry/reconstruction/wall_crossing 的完整 failure reason channel。",
            "minimum_interface": "每个 failed tracer 必须可按 support gate、wall crossing、numeric loss 或 explicit exit reason 归因，并按初始 mass/source 汇总。",
        })
    if summary["source_semantics_declared_count"] < summary["material_present_count"]:
        open_gaps.append({
            "id": "actual_release_source_semantics_provenance_missing",
            "severity": "P2",
            "evidence": "material.attrs.source_label_semantics and material/source_label",
            "finding": f"{summary['material_present_count'] - summary['source_semantics_declared_count']}/{summary['material_present_count']} 个 material artifact 没有显式说明 source_label 是 initial solver Mk proxy，而不是物理材料 lineage。",
            "minimum_interface": "持久化 source origin/lineage semantics；若只有 Mk proxy，必须保持 candidate-only 并禁止升级为材料真值。",
        })
    if policy_error:
        open_gaps.append({
            "id": "boundary_policy_link_unreadable",
            "severity": "P1",
            "evidence": "manifest.boundary_policy",
            "finding": policy_error,
            "minimum_interface": "sidecar 与每个案例的 open-face policy 必须可从 release root 安全解析。",
        })
    cross_resolution = _cross_resolution_audit(manifest["cases"])
    if cross_resolution["cross_resolution_pair_count"] == 0:
        open_gaps.append({
            "id": "actual_release_has_no_explicit_resolution_pair",
            "severity": "P2",
            "evidence": "manifest cases do not declare resolution_group_id/resolution_group",
            "finding": "当前 release 没有可审计的同一物理场景跨分辨率 pair；不能把不同 lineage/family 案例误当成 resolution convergence。",
            "minimum_interface": "下一轮显式声明 physical_case_id/resolution_group_id，并只做质量聚合或 explicit stable-key comparison。",
        })

    status = "candidate_only_rejected" if open_gaps or summary["formal_material_target_count"] == 0 else "candidate_contract_pass"
    return _json_value({
        "schema_version": SCHEMA_VERSION,
        "scope": "R4 tracer actual-scenario contract audit",
        "execution": {
            "backend": "h5py + NumPy CPU/static inspection",
            "gpu_used": False,
            "cuda_used": False,
            "cfd_solver_run": False,
            "gen_case_run": False,
            "production_files_modified": False,
            "tests_imported_by_audit": False,
        },
        "inputs": {
            "manifest": _relative(manifest_path, lab_root),
            "manifest_sha256": _sha256(manifest_path),
            "boundary_policy": _relative(policy_path, lab_root) if policy_path is not None else None,
            "boundary_policy_sha256": _sha256(policy_path) if policy_path is not None else None,
            "trajectory_protocol": "protocol/trajectory-v0.1.md",
            "actual_case_count": len(manifest["cases"]),
        },
        "method": {
            "seed_identity": "compound (particle_zone, particle_id) key within one HDF5; no array-position seed matching",
            "mass_denominator": "initial fluid mass / represented initial material mass; failed mass is retained, not renormalized",
            "cadence": "median diff(time) is saved velocity/trajectory cadence; integration substeps are a separate explicit field",
            "support_failure": "terminal material invalidity is reported by initial mass/source; reason attribution is only claimed when persisted evidence exists",
            "wall_open_face": "sidecar geometry, component policy, material wall_visibility provenance, and candidate/formal admission are separate checks",
            "source_destination": "only explicit destination specs are executable; legacy world-x bins are never promoted to formal destinations",
            "cross_resolution": "source×destination mass aggregates or explicit stable keys; array index matching is forbidden",
        },
        "implementation_inventory": inventory,
        "cases": cases,
        "cross_resolution": cross_resolution,
        "summary": summary,
        "open_interface_gaps": open_gaps,
        "policy_error": policy_error,
        "decision": {
            "status": status,
            "formal_ready": False,
            "material_transport_target_admitted": False,
            "reason": "contract evidence is candidate-only and at least one producer/consumer or destination interface remains open",
        },
    })


def render_markdown(report: Mapping[str, Any]) -> str:
    summary = report["summary"]
    cases = report["cases"]
    lines = [
        "# R4 tracer actual-scenario contract audit",
        "",
        "状态：**candidate-only / rejected；本轮仅 CPU/static audit，未启动 CFD、GenCase、CUDA 或 GPU。**",
        "",
        "本报告把已有 synthetic 反例推进到已物化 development release 的实际 HDF5、sidecar、manifest 和 G4 输入边界。结构字段通过不等于材料轨迹或 wall-aware transport 已被正式接纳。",
        "",
        "## 结论摘要",
        "",
        f"- release cases：{summary['case_count']}；带 material group：{summary['material_present_count']}；seed/source 结构通过：{summary['seed_material_contract_pass_count']}；source semantics 明示：{summary['source_semantics_declared_count']}。",
        f"- 质量权重闭合：{summary['mass_weight_closure_pass_count']}/{summary['material_present_count']}；输出 cadence 声明匹配：{summary['output_cadence_pass_count']}/{summary['case_count']}。",
        f"- 显式积分子步 provenance：{summary['explicit_substeps_count']}/{summary['material_present_count']}；完整 support failure channel：{summary['support_diagnostic_complete_count']}/{summary['material_present_count']}。",
        f"- sidecar 结构通过：{summary['sidecar_structural_pass_count']}；candidate open-face policy 通过：{summary['candidate_open_face_semantics_pass_count']}；正式 wall-aware admission：{summary['formal_wall_visibility_admission_count']}。",
        f"- destination spec：{summary['destination_spec_present_count']}；source-destination closure：{summary['source_destination_closure_pass_count']}；formal material target：{summary['formal_material_target_count']}。",
        f"- 已报告 terminal failed mass：{summary['failed_mass_kg']:.9g} kg，占已表示初始质量 {summary['failed_mass_fraction_of_represented']:.6%}。",
        "",
        "## 逐案例实际证据",
        "",
        "| case | material/seed | weight closure | saved cadence | substeps | failed mass kg | wall/open-face | destination closure |",
        "|---|---|---|---|---|---:|---|---|",
    ]
    for case in cases:
        seed = case["seed_material"].get("status", "blocked")
        mass = case["mass_weights"].get("status", "blocked")
        cadence = case["cadence_and_integration"]
        substeps = cadence.get("substeps_per_saved_interval") if cadence else None
        failed = case["support_failure"].get("terminal_failed_mass_kg")
        wall = case["wall_open_face"].get("status", "blocked")
        destination = case["source_destination"].get("status", "blocked")
        lines.append(
            f"| `{case['case_id']}` | {seed} | {mass} | "
            f"{cadence.get('observed_saved_cadence_median_s', 'n/a')} s / {cadence.get('output_cadence_status', 'n/a')} | "
            f"{substeps if substeps is not None else 'missing'} | "
            f"{float(failed or 0.0):.9g} | {wall} | {destination} |"
        )
    lines.extend([
        "",
        "`failed mass` 使用 material 的初始 `mass_weight`，按每个 case 的 `source_label` 单独报告；没有把 surviving tracer 重新归一到 1。",
        "",
        "## Failed mass / source",
        "",
        "| case | source | initial represented mass kg | failed tracer count | failed mass kg | failed fraction | reason |",
        "|---|---:|---:|---:|---:|---:|---|",
    ])
    for case in cases:
        failure_by_source = case["support_failure"].get("failed_mass_by_source") or {}
        reason_by_source = case["support_failure"].get("failed_mass_by_source_and_reason") or {}
        initial_by_source = case["mass_weights"].get("per_source", {})
        for source in sorted(failure_by_source, key=int):
            failed_row = failure_by_source[source]
            initial_mass = float(initial_by_source.get(source, {}).get("represented_mass_weight_kg", 0.0))
            failed_mass = float(failed_row.get("mass_kg", 0.0))
            reasons = [
                reason for reason, detail in (reason_by_source.get(source) or {}).items()
                if float(detail.get("mass_kg", 0.0)) > 0.0
            ]
            lines.append(
                f"| `{case['case_id']}` | `{source}` | {initial_mass:.9g} | "
                f"{int(failed_row.get('tracer_count', 0))} | {failed_mass:.9g} | "
                f"{failed_mass / max(initial_mass, 1e-30):.6%} | "
                f"{', '.join(reasons) if reasons else 'none'} |"
            )
    lines.extend([
        "",
        "## 已有能力与实际缺口",
        "",
        "已有 production tracer 路径包括：source-stratified 初始 Mk seed、初始质量权重、Heun、独立 `frame_stride` 与 `substeps_per_interval`、ESS/几何秩/各向异性/重构误差 gate、有限三角面 visibility、rigid-pose 插值和 swept-wall 检查。G4 已拒绝显式 future fluid/free-body state，也能读取 sidecar 的 component geometry features。",
        "",
        "本 audit 在当前实际 artifact 中发现：",
        "",
    ])
    for gap in report["open_interface_gaps"]:
        lines.append(f"- **{gap['id']} ({gap['severity']})**：{gap['finding']} 证据：`{gap['evidence']}`。最小接口：{gap['minimum_interface']}")
    lines.extend([
        "",
        "## 反例 / 不可宣称项",
        "",
        "- 12 个 F1/F2/F3 case 有有限 sidecar，但 material attrs 仍是 `wall_visibility=not supplied in development pilot`；sidecar 存在不能追溯地让旧轨迹变成 wall-aware。",
        "- `F1_center_obstacle`、`F1_twin_obstacle`、`F3_baffled_slosh` 的 policy 含未确认 implicit cap；其余 candidate policy 也不是物理 admission。",
        "- `W05_F6_fine` 没有 material group 和 boundary sidecar，因此不能从它得到 material source、failed mass/source 或 wall/open-face 结论。",
        "- 现有 material group 的 failure 可按初始质量/source 报告，但 artifact 没有完整 support gate/ESS/geometry/reconstruction/wall-crossing reason channel；对 terminal failure 的 support-distance 只能是部分证据。",
        "- 当前 release 没有 destination specification；legacy world-x bins 不能替代 open-face/outlet/destination contract。",
        "",
        "## 跨分辨率规则",
        "",
        "固定排列置换 negative control：同一 source×destination mass table 换存储顺序后，质量聚合保持不变，而 naive array-index mismatch 为 `" + str(report["cross_resolution"]["permutation_negative_control"]["naive_array_index_mismatch_count"]) + "`。因此跨分辨率禁止按 array index matching；当前 release 也没有显式 resolution pair，不能把不同 lineage 当作 convergence。",
        "",
        "## 下一步最小真实场景实验（本轮未执行）",
        "",
        "建议只选 `W06_standard_slow_center`：复用已有 251 帧、约 0.01 s saved cadence 的 HDF5 和对应 moving-cup sidecar，不重跑 CFD。先冻结 cup/receiver/floor 的 open-face、rim、supporting 和 destination/outlet 语义，再用 32/64 个质量加权 seed × 1/4 个显式积分子步，在 sidecar provider 下做 CPU tracer rollout。",
        "",
        "实验输出必须同时保存：`substeps_per_saved_interval`、实际子步 dt、每步 support gate/ESS/geometry/reconstruction、wall crossing、source×destination mass（含 `in_domain_unclassified` 与 `numerical_loss`/explicit exit reason）及 failed mass/source。只比较质量分布和事件统计，不按跨分辨率数组位置对齐；完成后再决定是否值得扩展到第二个 case。",
        "",
        "机器可读证据由 `scripts/r4_tracer_actual_scenario_audit.py` 生成。",
        "",
    ])
    return "\n".join(lines)


def write_outputs(report: Mapping[str, Any], report_path: Path = DEFAULT_REPORT, markdown_path: Path = DEFAULT_MARKDOWN) -> None:
    report_path = Path(report_path)
    markdown_path = Path(markdown_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    markdown_path.write_text(render_markdown(report))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--print-json", action="store_true")
    args = parser.parse_args()
    report = build_report(args.manifest)
    write_outputs(report, args.report, args.markdown)
    if args.print_json:
        print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(f"wrote {args.report}")
        print(f"wrote {args.markdown}")


if __name__ == "__main__":
    main()
