#!/usr/bin/env python3
"""Run one bounded, auditable L2-R B2R training/evaluation attempt.

This worker is intentionally disjoint from ``l2_resume`` and from the B2R
preparation scheduler.  It reads the prepared study manifest, executes at
most one route/seed attempt, and writes an attempt record plus the complete
logical/evaluation failure denominator under an explicit output directory.

The worker consumes the current-state graph contract from ``l2_b2r_model``.
The raw and hybrid routes use one shared graph trunk; hybrid changes only the
declared known-control operator.  No wall correction, output projection, or
clipping is performed by this file.

The numerical result is diagnostic only.  A finite one-step evaluator is not a
physical qualification gate, so a successful bounded attempt records
``model_physical_pass=unknown`` rather than manufacturing a physical pass.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import time
import traceback
import uuid
from typing import Any, Iterable, Mapping

import h5py
import numpy as np
import torch
from torch import nn

try:
    from scripts.l2_b2r_contract import (
        B2RContractError,
        R2Gate,
        StudySpec,
        validate_preparation_manifest,
    )
    from scripts.l2_b2r_model import (
        GraphBatch,
        build_radius_graph,
        model_for,
        validate_causal_payload,
    )
    from scripts.l2_b2r_records import (
        build_failure_denominator,
        create_attempt_record,
        validate_failure_denominator,
        write_attempt_record,
    )
except ModuleNotFoundError:  # direct ``python scripts/l2_b2r_train.py``
    from l2_b2r_contract import B2RContractError, R2Gate, StudySpec, validate_preparation_manifest
    from l2_b2r_model import GraphBatch, build_radius_graph, model_for, validate_causal_payload
    from l2_b2r_records import (
        build_failure_denominator,
        create_attempt_record,
        validate_failure_denominator,
        write_attempt_record,
    )


LAB = Path(__file__).resolve().parents[1]
DEFAULT_STUDY = LAB / "campaigns/l2-multifamily/resume-c6b28c8/b2r-study.json"
REGISTRY_SCHEMA = "l2.f3.canonical_manifest.v1"
WORKER_SCHEMA = "l2r.b2r.bounded_worker.v1"
ATTEMPT_REPORT_SCHEMA = "l2r.b2r.bounded_attempt_report.v1"

# Hard safety ceilings.  The CLI may choose a smaller bounded budget, but a
# single invocation cannot silently become a six-run or long-training launch.
HARD_MAX_STEPS = 256
HARD_MAX_FRAMES = 64
HARD_MAX_PARTICLES = 1024
HARD_MAX_SECONDS = 300.0
HARD_MAX_GPU_MEMORY_MB = 8192
HARD_MAX_NEIGHBORS = 64

WALL_BOUNDS = {
    "xmin": -0.45,
    "xmax": 0.45,
    "ymin": -0.09,
    "ymax": 0.09,
    "zmin": 0.0,
    "closed_faces": ("bottom", "left", "right", "front", "back"),
    "open_faces": ("top",),
}
BOUNDARY_REFERENCE_LENGTH_M = 0.1
REQUIRED_HDF5_DATASETS = (
    "time",
    "position",
    "velocity",
    "mass",
    "density",
    "pressure",
    "particle_id",
    "valid",
)


class WorkerGuardError(RuntimeError):
    """A deliberate preflight or bounded-budget rejection."""

    def __init__(self, message: str, *, category: str = "guard_rejected") -> None:
        super().__init__(message)
        self.category = category


class BudgetGuardError(WorkerGuardError):
    """The requested or observed work exceeded the hard bounded budget."""

    def __init__(self, message: str) -> None:
        super().__init__(message, category="budget_rejected")


@dataclass(frozen=True)
class BoundedBudget:
    max_steps: int = 16
    max_frames: int = 4
    max_particles: int = 128
    max_seconds: float = 120.0
    max_gpu_memory_mb: int = 4096
    max_neighbors: int = 8

    def validate(self) -> None:
        integer_fields = (
            ("max_steps", self.max_steps, 1, HARD_MAX_STEPS),
            ("max_frames", self.max_frames, 2, HARD_MAX_FRAMES),
            ("max_particles", self.max_particles, 2, HARD_MAX_PARTICLES),
            ("max_neighbors", self.max_neighbors, 1, HARD_MAX_NEIGHBORS),
            ("max_gpu_memory_mb", self.max_gpu_memory_mb, 256, HARD_MAX_GPU_MEMORY_MB),
        )
        for name, value, minimum, maximum in integer_fields:
            if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
                raise BudgetGuardError(
                    f"{name}={value!r} is outside bounded worker range [{minimum}, {maximum}]"
                )
        if (
            isinstance(self.max_seconds, bool)
            or not isinstance(self.max_seconds, (int, float))
            or not math.isfinite(float(self.max_seconds))
            or not 1.0 <= float(self.max_seconds) <= HARD_MAX_SECONDS
        ):
            raise BudgetGuardError(
                f"max_seconds={self.max_seconds!r} is outside bounded worker range [1, {HARD_MAX_SECONDS}]"
            )


@dataclass(frozen=True)
class Transition:
    """One current graph and a next-position displacement target."""

    case_id: str
    frame_index: int
    batch: GraphBatch
    target_displacement: torch.Tensor


@dataclass(frozen=True)
class SourceCase:
    case_id: str
    split: str
    hdf5_path: Path
    control_path: Path
    expected_hdf5_sha256: str | None
    expected_control_sha256: str | None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any, *, overwrite: bool = False) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(path)


def _resolve_lab_path(value: str | Path) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = LAB / candidate
    candidate = candidate.resolve()
    try:
        candidate.relative_to(LAB.resolve())
    except ValueError as error:
        raise WorkerGuardError(f"source path escapes the L2R lab: {candidate}", category="missing_data") from error
    return candidate


def _device_from_argument(value: str, *, allow_cpu: bool) -> torch.device:
    normalized = str(value).strip().lower()
    if normalized == "auto":
        if torch.cuda.is_available():
            return torch.device("cuda:0")
        if allow_cpu:
            return torch.device("cpu")
        raise WorkerGuardError(
            "CUDA is unavailable; pass --allow-cpu for an explicit CPU diagnostic attempt",
            category="device_rejected",
        )
    if normalized == "cpu":
        if not allow_cpu:
            raise WorkerGuardError(
                "CPU execution requires explicit --allow-cpu", category="device_rejected"
            )
        return torch.device("cpu")
    if normalized == "cuda":
        normalized = "cuda:0"
    if not normalized.startswith("cuda:"):
        raise WorkerGuardError(f"unsupported device {value!r}", category="device_rejected")
    if not torch.cuda.is_available():
        raise WorkerGuardError("CUDA device requested but CUDA is unavailable", category="device_rejected")
    try:
        index = int(normalized.split(":", 1)[1])
    except ValueError as error:
        raise WorkerGuardError(f"invalid CUDA device {value!r}", category="device_rejected") from error
    if index < 0 or index >= torch.cuda.device_count():
        raise WorkerGuardError(
            f"CUDA device index {index} is outside visible device count {torch.cuda.device_count()}",
            category="device_rejected",
        )
    return torch.device("cuda", index)


def _physical_gpu_index(device: torch.device, explicit: int | None) -> int | None:
    if device.type != "cuda":
        return None
    if explicit is not None:
        return explicit
    visible = os.environ.get("CUDA_VISIBLE_DEVICES", "").strip()
    logical_index = int(device.index or 0)
    if visible:
        tokens = [token.strip() for token in visible.split(",")]
        if logical_index < len(tokens) and tokens[logical_index].isdigit():
            return int(tokens[logical_index])
    return logical_index


def _device_preflight(device: torch.device, budget: BoundedBudget, explicit_gpu_index: int | None) -> dict[str, Any]:
    if device.type == "cpu":
        return {
            "device": "cpu",
            "gpu_index": None,
            "gpu_name": None,
            "free_memory_mb": None,
            "total_memory_mb": None,
        }
    index = int(device.index or 0)
    free, total = torch.cuda.mem_get_info(index)
    free_mb = float(free) / (1024 * 1024)
    total_mb = float(total) / (1024 * 1024)
    if free_mb < float(budget.max_gpu_memory_mb):
        raise WorkerGuardError(
            f"visible CUDA device has only {free_mb:.1f} MiB free, below the {budget.max_gpu_memory_mb} MiB budget",
            category="device_rejected",
        )
    torch.cuda.reset_peak_memory_stats(index)
    return {
        "device": str(device),
        "gpu_index": _physical_gpu_index(device, explicit_gpu_index),
        # The torch runtime exposes the device name here, not a stable UUID;
        # leave the attempt-record UUID null rather than mislabelling the name.
        "gpu_uuid": None,
        "gpu_name": torch.cuda.get_device_name(index),
        "free_memory_mb": free_mb,
        "total_memory_mb": total_mb,
    }


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as error:
        raise WorkerGuardError(f"invalid JSON: {path}", category="contract_rejected") from error


def load_study_manifest(path: str | Path) -> tuple[Path, dict[str, Any]]:
    study_path = _resolve_lab_path(path)
    if not study_path.is_file():
        raise WorkerGuardError(f"study manifest is missing: {study_path}", category="missing_data")
    manifest = _load_json(study_path)
    try:
        validate_preparation_manifest(manifest)
    except B2RContractError as error:
        raise WorkerGuardError(str(error), category="contract_rejected") from error
    dependency = manifest.get("dependencies", {})
    r0 = dependency.get("R0", {})
    r2 = dependency.get("R2", {})
    if not manifest.get("launch_allowed") or manifest.get("status") != "prepared_not_launched":
        raise WorkerGuardError(
            "B2R study is not explicitly launch_allowed/prepared_not_launched",
            category="dependency_rejected",
        )
    if r0.get("status") != "verified_for_design":
        raise WorkerGuardError("R0 design dependency is not verified", category="dependency_rejected")
    if r2.get("status") != "satisfied" or not r2.get("launch_allowed"):
        raise WorkerGuardError("R2 dependency is not explicitly satisfied", category="dependency_rejected")
    model_contract = manifest.get("model_contract", {})
    routes = model_contract.get("routes", {})
    if model_contract.get("qualification_claim") is not False:
        raise WorkerGuardError("study model contract must not claim qualification", category="contract_rejected")
    for route in ("raw", "hybrid"):
        route_contract = routes.get(route, {})
        if route_contract.get("posthoc_wall_projection") is not False:
            raise WorkerGuardError(f"{route} route permits an unreported wall correction", category="contract_rejected")
        if route_contract.get("output_clipping") is not False:
            raise WorkerGuardError(f"{route} route permits output clipping", category="contract_rejected")
    registry = manifest.get("data_contract", {}).get("evaluation_case_registry", {})
    ids = registry.get("physical_case_ids")
    if not isinstance(ids, list) or not ids or len(set(ids)) != len(ids):
        raise WorkerGuardError("study manifest has no unique physical evaluation denominator", category="contract_rejected")
    return study_path, manifest


def study_spec_from_manifest(manifest: Mapping[str, Any]) -> StudySpec:
    registry = manifest["data_contract"]["evaluation_case_registry"]
    r2 = manifest["dependencies"]["R2"]
    gate = R2Gate(
        status="satisfied",
        launch_allowed=True,
        reason=str(r2.get("reason", "explicit R2 evidence supplied")),
        source=dict(r2.get("source") or {}),
    )
    return StudySpec(
        evaluation_case_ids=tuple(registry["physical_case_ids"]),
        evaluation_case_registry=str(registry["source"]["path"]),
        r2_gate=gate,
        r0_verified=True,
    )


def load_registry_rows(manifest: Mapping[str, Any]) -> tuple[Path, dict[str, dict[str, Any]]]:
    source = manifest["data_contract"]["evaluation_case_registry"]["source"]
    registry_path = _resolve_lab_path(source["path"])
    if not registry_path.is_file():
        raise WorkerGuardError(f"canonical case registry is missing: {registry_path}", category="missing_data")
    payload = _load_json(registry_path)
    if payload.get("schema") != REGISTRY_SCHEMA or not isinstance(payload.get("cases"), list):
        raise WorkerGuardError("canonical case registry has an unexpected schema", category="contract_rejected")
    rows: dict[str, dict[str, Any]] = {}
    for row in payload["cases"]:
        if not isinstance(row, Mapping) or not isinstance(row.get("case_id"), str):
            raise WorkerGuardError("canonical registry contains an invalid case row", category="contract_rejected")
        case_id = str(row["case_id"])
        if case_id in rows:
            raise WorkerGuardError(f"duplicate canonical case ID: {case_id}", category="contract_rejected")
        rows[case_id] = dict(row)
    expected = set(manifest["data_contract"]["evaluation_case_registry"]["physical_case_ids"])
    actual_eval = {
        row.get("physical_case_id", row.get("case_id"))
        for row in rows.values()
        if row.get("split") in {"validation", "test"}
    }
    if expected != actual_eval:
        raise WorkerGuardError(
            "study evaluation denominator differs from canonical validation/test registry",
            category="contract_rejected",
        )
    return registry_path, rows


def resolve_source_case(row: Mapping[str, Any], *, expected_split: str) -> SourceCase:
    if row.get("split") != expected_split:
        raise WorkerGuardError(
            f"case {row.get('case_id')} has split {row.get('split')!r}, expected {expected_split!r}",
            category="data_rejected",
        )
    hdf5_value = row.get("hdf5")
    control_value = (row.get("source_evidence") or {}).get("control", {}).get("path")
    if not isinstance(hdf5_value, str) or not isinstance(control_value, str):
        raise WorkerGuardError(
            f"case {row.get('case_id')} lacks registered HDF5/control paths", category="missing_data"
        )
    hdf5_path = _resolve_lab_path(hdf5_value)
    control_path = _resolve_lab_path(control_value)
    if not hdf5_path.is_file() or not control_path.is_file():
        missing = [str(path) for path in (hdf5_path, control_path) if not path.is_file()]
        raise WorkerGuardError("missing B2R source data: " + ", ".join(missing), category="missing_data")
    expected_hdf5 = (row.get("file") or {}).get("sha256")
    expected_control = (row.get("source_evidence") or {}).get("control", {}).get("sha256")
    return SourceCase(
        case_id=str(row["case_id"]),
        split=expected_split,
        hdf5_path=hdf5_path,
        control_path=control_path,
        expected_hdf5_sha256=expected_hdf5 if isinstance(expected_hdf5, str) else None,
        expected_control_sha256=expected_control if isinstance(expected_control, str) else None,
    )


def _parse_control(path: Path) -> tuple[np.ndarray, np.ndarray]:
    rows: list[list[float]] = []
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = [field.strip() for field in line.split(";")]
        try:
            values = [float(field) for field in fields]
        except ValueError:
            # A non-comment column header is allowed once.
            if not rows:
                continue
            raise WorkerGuardError(f"invalid control row in {path}: {raw_line!r}", category="data_rejected")
        if len(values) < 4:
            raise WorkerGuardError(f"control row has fewer than four columns: {path}", category="data_rejected")
        rows.append(values)
    if not rows:
        raise WorkerGuardError(f"control file has no numeric rows: {path}", category="missing_data")
    array = np.asarray(rows, dtype=np.float64)
    times = array[:, 0]
    acceleration = array[:, 1:4]
    if not np.isfinite(array).all() or np.any(np.diff(times) <= 0):
        raise WorkerGuardError(f"control time/values are not finite and strictly increasing: {path}", category="data_rejected")
    return times, acceleration


def _frame_indices(frame_count: int, max_frames: int) -> np.ndarray:
    if frame_count < 2:
        raise WorkerGuardError("trajectory needs at least two frames", category="missing_data")
    if frame_count - 1 < max_frames:
        raise WorkerGuardError(
            f"requested {max_frames} transitions but trajectory has only {frame_count - 1}",
            category="budget_rejected",
        )
    values = np.rint(np.linspace(0, frame_count - 2, max_frames)).astype(np.int64)
    values = np.unique(values)
    if len(values) != max_frames:
        raise WorkerGuardError("frame budget collapsed to duplicate transition indices", category="data_rejected")
    return values


def _geometry_features(position: np.ndarray, *, boundary_radius_m: float) -> np.ndarray:
    xmin, xmax = WALL_BOUNDS["xmin"], WALL_BOUNDS["xmax"]
    ymin, ymax = WALL_BOUNDS["ymin"], WALL_BOUNDS["ymax"]
    zmin = WALL_BOUNDS["zmin"]
    distances = np.column_stack(
        (
            position[:, 0] - xmin,
            xmax - position[:, 0],
            position[:, 1] - ymin,
            ymax - position[:, 1],
            position[:, 2] - zmin,
        )
    )
    normals = np.asarray(
        (
            (-1.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, -1.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, 0.0, -1.0),
        ),
        dtype=np.float32,
    )
    nearest = np.argmin(distances, axis=1)
    nearest_distance = distances[np.arange(len(position)), nearest]
    nearest_normal = normals[nearest]
    boundary_presence = (nearest_distance <= boundary_radius_m).astype(np.float32)
    return np.column_stack(
        (
            nearest_distance / BOUNDARY_REFERENCE_LENGTH_M,
            nearest_normal,
            boundary_presence,
        )
    ).astype(np.float32)


def _node_features(
    position: np.ndarray,
    density: np.ndarray,
    pressure: np.ndarray,
    mass: np.ndarray,
    *,
    references: tuple[float, float, float],
    boundary_radius_m: float,
) -> np.ndarray:
    mass_reference, density_reference, pressure_reference = references
    geometry = _geometry_features(position, boundary_radius_m=boundary_radius_m)
    features = np.column_stack(
        (
            mass / mass_reference,
            density / density_reference,
            pressure / pressure_reference,
            geometry,
        )
    ).astype(np.float32)
    if features.shape[1] != 8 or not np.isfinite(features).all():
        raise WorkerGuardError("current node features are missing or non-finite", category="data_rejected")
    return features


def _case_transitions(
    source: SourceCase,
    *,
    budget: BoundedBudget,
    device: torch.device,
    verify_hashes: bool = False,
) -> tuple[list[Transition], dict[str, Any]]:
    if verify_hashes:
        observed_hdf5 = sha256_file(source.hdf5_path)
        observed_control = sha256_file(source.control_path)
        if source.expected_hdf5_sha256 and observed_hdf5 != source.expected_hdf5_sha256:
            raise WorkerGuardError(f"HDF5 hash mismatch for {source.case_id}", category="data_rejected")
        if source.expected_control_sha256 and observed_control != source.expected_control_sha256:
            raise WorkerGuardError(f"control hash mismatch for {source.case_id}", category="data_rejected")
    else:
        observed_hdf5 = None
        observed_control = None
    control_times, control_acceleration = _parse_control(source.control_path)
    with h5py.File(source.hdf5_path, "r") as handle:
        missing = [name for name in REQUIRED_HDF5_DATASETS if name not in handle]
        if missing:
            raise WorkerGuardError(
                f"{source.case_id} is missing HDF5 datasets: {', '.join(missing)}", category="missing_data"
            )
        time_dataset = handle["time"]
        position_dataset = handle["position"]
        velocity_dataset = handle["velocity"]
        t_count = int(time_dataset.shape[0])
        if position_dataset.ndim != 3 or tuple(position_dataset.shape) != (t_count, int(handle["particle_id"].shape[0]), 3):
            raise WorkerGuardError(f"{source.case_id} has invalid position shape", category="data_rejected")
        if velocity_dataset.shape != position_dataset.shape:
            raise WorkerGuardError(f"{source.case_id} has invalid velocity shape", category="data_rejected")
        for name in ("mass", "density", "pressure", "valid"):
            if handle[name].shape != (t_count, position_dataset.shape[1]):
                raise WorkerGuardError(f"{source.case_id} has invalid {name} shape", category="data_rejected")
        frame_indices = _frame_indices(t_count, budget.max_frames)
        valid_current = np.asarray(handle["valid"][frame_indices], dtype=bool)
        valid_next = np.asarray(handle["valid"][frame_indices + 1], dtype=bool)
        common = np.flatnonzero(np.all(valid_current & valid_next, axis=0))
        if len(common) < min(8, budget.max_particles):
            raise WorkerGuardError(
                f"{source.case_id} has only {len(common)} particles valid across bounded transitions",
                category="data_rejected",
            )
        particle_count = min(len(common), budget.max_particles)
        if particle_count < 2:
            raise WorkerGuardError("bounded graph needs at least two particles", category="data_rejected")
        selected = common[np.rint(np.linspace(0, len(common) - 1, particle_count)).astype(np.int64)]
        selected = np.unique(selected)
        if len(selected) != particle_count:
            raise WorkerGuardError("particle sampling produced duplicate identities", category="data_rejected")
        particle_ids = np.asarray(handle["particle_id"][selected], dtype=np.int64)
        if len(np.unique(particle_ids)) != len(particle_ids):
            raise WorkerGuardError("particle_id is not unique in bounded graph", category="data_rejected")
        mass_reference_values = np.asarray(handle["mass"][0, selected], dtype=np.float64)
        density_reference_values = np.asarray(handle["density"][0, selected], dtype=np.float64)
        pressure_reference_values = np.asarray(handle["pressure"][0, selected], dtype=np.float64)
        if (
            not np.isfinite(mass_reference_values).all()
            or not np.isfinite(density_reference_values).all()
            or not np.isfinite(pressure_reference_values).all()
            or np.any(mass_reference_values <= 0)
        ):
            raise WorkerGuardError("initial material references are invalid", category="data_rejected")
        references = (
            float(np.mean(mass_reference_values)),
            max(abs(float(np.mean(density_reference_values))), 1.0),
            max(abs(float(np.mean(pressure_reference_values))), 1.0),
        )
        transitions: list[Transition] = []
        for frame_index in frame_indices.tolist():
            time_current = float(time_dataset[frame_index])
            time_next = float(time_dataset[frame_index + 1])
            interval = time_next - time_current
            if not math.isfinite(interval) or interval <= 0:
                raise WorkerGuardError(f"non-positive frame interval in {source.case_id}", category="data_rejected")
            position = np.asarray(position_dataset[frame_index, selected], dtype=np.float32)
            next_position = np.asarray(position_dataset[frame_index + 1, selected], dtype=np.float32)
            velocity = np.asarray(velocity_dataset[frame_index, selected], dtype=np.float32)
            density = np.asarray(handle["density"][frame_index, selected], dtype=np.float32)
            pressure = np.asarray(handle["pressure"][frame_index, selected], dtype=np.float32)
            mass = np.asarray(handle["mass"][frame_index, selected], dtype=np.float32)
            if not all(np.isfinite(array).all() for array in (position, next_position, velocity, density, pressure, mass)):
                raise WorkerGuardError(
                    f"non-finite current/target data in {source.case_id} frame {frame_index}",
                    category="data_rejected",
                )
            control = np.asarray(
                [np.interp(time_current, control_times, control_acceleration[:, axis]) for axis in range(3)],
                dtype=np.float32,
            )
            features = _node_features(
                position,
                density,
                pressure,
                mass,
                references=references,
                boundary_radius_m=0.02,
            )
            position_tensor = torch.from_numpy(position)
            velocity_tensor = torch.from_numpy(velocity)
            node_tensor = torch.from_numpy(features)
            control_tensor = torch.from_numpy(control)
            edge_index, edge_features = build_radius_graph(
                position_tensor,
                velocity_tensor,
                torch.from_numpy(particle_ids),
                radius_m=0.02,
                max_neighbors=budget.max_neighbors,
            )
            batch = GraphBatch(
                position=position_tensor,
                velocity=velocity_tensor,
                node_features=node_tensor,
                edge_index=edge_index,
                edge_features=edge_features,
                interval_s=float(interval),
                control_acceleration=control_tensor,
                particle_id=torch.from_numpy(particle_ids),
            )
            target = torch.from_numpy(next_position - position)
            transitions.append(
                Transition(
                    case_id=source.case_id,
                    frame_index=int(frame_index),
                    batch=batch,
                    target_displacement=target,
                )
            )
    return transitions, {
        "case_id": source.case_id,
        "split": source.split,
        "hdf5_path": str(source.hdf5_path),
        "control_path": str(source.control_path),
        "expected_hdf5_sha256": source.expected_hdf5_sha256,
        "expected_control_sha256": source.expected_control_sha256,
        "observed_hdf5_sha256": observed_hdf5,
        "observed_control_sha256": observed_control,
        "transition_count": len(transitions),
        "particle_count": int(transitions[0].batch.position.shape[0]) if transitions else 0,
        "future_state_used_as_input": False,
        "future_position_used_only_as_supervision_target": True,
        "node_feature_names": [
            "mass_over_reference",
            "density_over_reference",
            "pressure_over_reference",
            "boundary_distance_over_length",
            "boundary_normal_x",
            "boundary_normal_y",
            "boundary_normal_z",
            "boundary_presence",
        ],
        "geometry_contract": {
            "wall_bounds": dict(WALL_BOUNDS),
            "reference_length_m": BOUNDARY_REFERENCE_LENGTH_M,
            "boundary_presence_radius_m": 0.02,
        },
    }


class SharedRouteModel(nn.Module):
    """One graph trunk with two explicit route operators."""

    def __init__(self, *, node_features: int, edge_features: int, hidden: int, message_steps: int) -> None:
        super().__init__()
        # ``GraphDynamicsModel``'s route-independent encoder/message blocks and
        # decoder are the shared trunk.  Its raw route only exposes the signal;
        # this wrapper applies the declared hybrid prior explicitly below.
        self.graph_trunk = model_for(
            route="raw",
            node_features=node_features,
            edge_features=edge_features,
            hidden=hidden,
            message_steps=message_steps,
        )

    @staticmethod
    def _control_rows(control: torch.Tensor, count: int) -> torch.Tensor:
        if control.ndim == 1:
            return control.expand(count, -1)
        if control.shape[0] == 1:
            return control.expand(count, -1)
        if control.shape[0] == count:
            return control
        raise ValueError("control rows do not match graph particle count")

    def forward(
        self,
        batch: GraphBatch,
        *,
        route: str,
        return_diagnostics: bool = False,
    ) -> torch.Tensor | tuple[torch.Tensor, dict[str, Any]]:
        if route not in {"raw", "hybrid"}:
            raise ValueError(f"unsupported B2R route: {route}")
        signal, base_diagnostics = self.graph_trunk(batch, return_diagnostics=True)
        if route == "raw":
            prior = torch.zeros_like(signal)
            correction = torch.zeros_like(signal)
            displacement = signal
        else:
            control = self._control_rows(batch.control_acceleration, batch.position.shape[0])
            interval = torch.as_tensor(batch.interval_s, device=batch.position.device, dtype=batch.position.dtype).reshape(())
            # The sole hybrid prior is the declared known-control operator.
            prior = batch.velocity * interval + 0.5 * control * interval.square()
            correction = 0.5 * signal * interval.square()
            displacement = prior + correction
        diagnostics = {
            "route": route,
            "shared_graph_trunk": True,
            "prior_displacement": prior,
            "residual_displacement": correction,
            "residual_displacement_l2": torch.linalg.vector_norm(correction, dim=-1),
            "residual_trigger_count": int((torch.linalg.vector_norm(correction, dim=-1) > 0).sum().item()),
            "correction_l2_mean": torch.linalg.vector_norm(correction, dim=-1).mean(),
            "correction_l2_max": torch.linalg.vector_norm(correction, dim=-1).max(),
            "prior_and_residual_cost": {
                "prior_vector_ops_per_particle": 12,
                "residual_vector_ops_per_particle": 6,
                "message_passing_steps": int(self.graph_trunk.message_steps),
            },
            "posthoc_wall_projection": False,
            "output_clipping": False,
            "base_route_signal": base_diagnostics.get("route"),
        }
        return (displacement, diagnostics) if return_diagnostics else displacement


def _move_batch(batch: GraphBatch, device: torch.device) -> GraphBatch:
    return GraphBatch(
        position=batch.position.to(device),
        velocity=batch.velocity.to(device),
        node_features=batch.node_features.to(device),
        edge_index=batch.edge_index.to(device),
        edge_features=batch.edge_features.to(device),
        interval_s=batch.interval_s,
        control_acceleration=batch.control_acceleration.to(device),
        particle_id=batch.particle_id.to(device) if batch.particle_id is not None else None,
    )


def _seed_everything(seed: int) -> None:
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def _check_elapsed(started: float, budget: BoundedBudget, stage: str) -> None:
    elapsed = time.monotonic() - started
    if elapsed > float(budget.max_seconds):
        raise BudgetGuardError(f"{stage} exceeded max_seconds={budget.max_seconds}")


def _finite_scalar(value: torch.Tensor, name: str) -> float:
    if not torch.isfinite(value).all():
        raise WorkerGuardError(f"{name} became non-finite", category="numerical_failure")
    return float(value.detach().cpu())


def _train_model(
    model: SharedRouteModel,
    transitions: list[Transition],
    *,
    route: str,
    seed: int,
    device: torch.device,
    budget: BoundedBudget,
    learning_rate: float,
    started: float,
) -> dict[str, Any]:
    _seed_everything(seed)
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    model.train()
    losses: list[float] = []
    for step in range(budget.max_steps):
        _check_elapsed(started, budget, "training")
        transition = transitions[step % len(transitions)]
        batch = _move_batch(transition.batch, device)
        target = transition.target_displacement.to(device)
        prediction = model(batch, route=route)
        loss = torch.mean((prediction - target).square())
        _finite_scalar(loss, "training loss")
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        for parameter in model.parameters():
            if parameter.grad is not None and not torch.isfinite(parameter.grad).all():
                raise WorkerGuardError("training gradient became non-finite", category="numerical_failure")
        optimizer.step()
        losses.append(_finite_scalar(loss, "training loss"))
        if device.type == "cuda":
            peak_mb = float(torch.cuda.max_memory_allocated(device)) / (1024 * 1024)
            if peak_mb > budget.max_gpu_memory_mb:
                raise BudgetGuardError(
                    f"training peak allocation {peak_mb:.1f} MiB exceeded {budget.max_gpu_memory_mb} MiB"
                )
    return {
        "steps_requested": budget.max_steps,
        "steps_completed": len(losses),
        "loss_first": losses[0],
        "loss_last": losses[-1],
        "loss_min": min(losses),
        "optimizer": "Adam",
        "learning_rate": learning_rate,
        "training_completed": True,
    }


def _evaluate_model(
    model: SharedRouteModel,
    transitions: list[Transition],
    *,
    route: str,
    device: torch.device,
    started: float,
    budget: BoundedBudget,
) -> dict[str, Any]:
    model.eval()
    losses: list[float] = []
    max_abs_displacement = 0.0
    residual_norms: list[float] = []
    with torch.no_grad():
        for transition in transitions:
            _check_elapsed(started, budget, "evaluation")
            batch = _move_batch(transition.batch, device)
            target = transition.target_displacement.to(device)
            prediction, diagnostics = model(batch, route=route, return_diagnostics=True)
            loss = torch.mean((prediction - target).square())
            losses.append(_finite_scalar(loss, "evaluation loss"))
            if not torch.isfinite(prediction).all():
                raise WorkerGuardError("evaluation prediction became non-finite", category="numerical_failure")
            max_abs_displacement = max(max_abs_displacement, float(prediction.abs().max().detach().cpu()))
            residual_norms.extend(float(value) for value in diagnostics["residual_displacement_l2"].detach().cpu().tolist())
    if not losses:
        raise WorkerGuardError("evaluation produced no rows", category="data_rejected")
    return {
        "evaluation_completed": True,
        "transition_count": len(losses),
        "mse_mean": float(np.mean(losses)),
        "mse_max": float(np.max(losses)),
        "prediction_max_abs_displacement": max_abs_displacement,
        "residual_displacement_l2_mean": float(np.mean(residual_norms)) if residual_norms else 0.0,
        "residual_displacement_l2_max": float(np.max(residual_norms)) if residual_norms else 0.0,
        "model_physical_pass": "unknown",
        "physical_verdict_reason": "bounded diagnostic evaluator is not a physical qualification gate",
        "posthoc_wall_projection": False,
        "output_clipping": False,
    }


def _safe_case_id(value: str, field: str) -> str:
    if not isinstance(value, str) or not value or any(character in value for character in "/\\\n\r\t"):
        raise WorkerGuardError(f"invalid {field}: {value!r}", category="contract_rejected")
    return value


def _attempt_id(route: str, seed: int, explicit: str | None) -> str:
    if explicit:
        _safe_case_id(explicit, "execution_attempt_id")
        return explicit
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + f"-{route}-seed{seed}-{uuid.uuid4().hex[:8]}"


def _record_denominator(
    *,
    output_dir: Path,
    spec: StudySpec,
    attempt_record: Mapping[str, Any],
    evaluation_rows: Iterable[Mapping[str, Any]],
    overwrite: bool,
) -> tuple[dict[str, Any], Path]:
    denominator = build_failure_denominator(spec, [attempt_record], evaluation_results=evaluation_rows)
    validate_failure_denominator(denominator)
    path = output_dir / "failure-denominator.json"
    _write_json(path, denominator, overwrite=overwrite)
    return denominator, path


def run_attempt(args: argparse.Namespace) -> dict[str, Any]:
    started = time.monotonic()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    attempt_id = _attempt_id(args.route, args.seed, args.attempt_id)
    budget = BoundedBudget(
        max_steps=args.max_steps,
        max_frames=args.max_frames,
        max_particles=args.max_particles,
        max_seconds=args.max_seconds,
        max_gpu_memory_mb=args.max_gpu_memory_mb,
        max_neighbors=args.max_neighbors,
    )

    study_path, manifest = load_study_manifest(args.study)
    spec = study_spec_from_manifest(manifest)
    registry_path, rows = load_registry_rows(manifest)
    logical_run = next(
        row for row in spec.logical_runs if row["route"] == args.route and row["seed"] == args.seed
    )
    physical_case_ids = spec.evaluation_case_ids
    data_contract_sha = canonical_sha256(manifest["data_contract"])
    model_contract_sha = canonical_sha256(manifest["model_contract"])
    r2_block = manifest["dependencies"]["R2"]
    r2_report_sha = (r2_block.get("source") or {}).get("report_sha256")
    r2_evidence_sha = r2_report_sha if isinstance(r2_report_sha, str) and len(r2_report_sha) == 64 else canonical_sha256(r2_block)
    overwrite = bool(args.overwrite)
    for name in ("attempt.json", "attempt-report.json", "failure-denominator.json"):
        if (output_dir / name).exists() and not overwrite:
            raise FileExistsError(f"output already contains {name}; choose a new --output-dir or --overwrite")

    training_completed = False
    evaluation_completed = False
    evaluation_rows: list[dict[str, Any]] = []
    training_report: dict[str, Any] = {}
    evaluation_report: dict[str, Any] = {}
    data_report: dict[str, Any] = {}
    device_report: dict[str, Any] = {}
    failure_reason: str | None = None
    worker_exit_status = "zero"
    attempt_status = "completed"
    model_physical_pass = "unknown"
    exit_code = 0
    failure_category: str | None = None
    try:
        budget.validate()
        if (
            isinstance(args.learning_rate, bool)
            or not isinstance(args.learning_rate, (int, float))
            or not math.isfinite(float(args.learning_rate))
            or float(args.learning_rate) <= 0
        ):
            raise BudgetGuardError("learning_rate must be one finite positive number")
        device = _device_from_argument(args.device, allow_cpu=bool(args.allow_cpu))
        device_report = _device_preflight(device, budget, args.gpu_index)
        train_id = _safe_case_id(args.train_case_id, "train_case_id")
        eval_id = _safe_case_id(args.eval_case_id, "eval_case_id")
        if train_id not in rows:
            raise WorkerGuardError(f"unknown training case: {train_id}", category="missing_data")
        if eval_id not in rows:
            raise WorkerGuardError(f"unknown evaluation case: {eval_id}", category="missing_data")
        if eval_id not in physical_case_ids:
            raise WorkerGuardError(
                f"evaluation case {eval_id} is outside the declared physical denominator",
                category="contract_rejected",
            )
        train_source = resolve_source_case(rows[train_id], expected_split="train")
        eval_source = resolve_source_case(rows[eval_id], expected_split=str(rows[eval_id].get("split")))
        train_transitions, train_report = _case_transitions(
            train_source,
            budget=budget,
            device=device,
            verify_hashes=bool(args.verify_source_hashes),
        )
        eval_transitions, eval_report = _case_transitions(
            eval_source,
            budget=budget,
            device=device,
            verify_hashes=bool(args.verify_source_hashes),
        )
        data_report = {
            "train": train_report,
            "evaluation": eval_report,
            "registry_path": str(registry_path),
            "registry_sha256": sha256_file(registry_path),
            "study_path": str(study_path),
            "study_sha256": sha256_file(study_path),
        }
        validate_causal_payload(
            {
                "current_particle_position": True,
                "current_particle_velocity": True,
                "current_material_geometry_features": True,
                "current_prescribed_control": True,
                "current_time_interval": True,
            }
        )
        architecture = manifest["model_contract"]["architecture"]
        node_features = int(architecture["node_features"])
        edge_features = int(architecture["edge_features"])
        hidden = int(architecture["hidden"])
        message_steps = int(architecture["message_steps"])
        model = SharedRouteModel(
            node_features=node_features,
            edge_features=edge_features,
            hidden=hidden,
            message_steps=message_steps,
        ).to(device)
        training_report = _train_model(
            model,
            train_transitions,
            route=args.route,
            seed=args.seed,
            device=device,
            budget=budget,
            learning_rate=args.learning_rate,
            started=started,
        )
        training_completed = True
        evaluation_report = _evaluate_model(
            model,
            eval_transitions,
            route=args.route,
            device=device,
            started=started,
            budget=budget,
        )
        evaluation_completed = True
        evaluation_rows.append(
            {
                "logical_run_id": logical_run["logical_run_id"],
                "physical_case_id": eval_id,
                # The records contract reserves the ``unknown`` evaluation
                # bucket for a completed diagnostic with no physical verdict.
                "status": "unknown",
                "model_physical_pass": "unknown",
                "failure_reason": "bounded diagnostic evaluator is not a physical qualification gate",
            }
        )
        checkpoint_path = output_dir / "model.pt"
        if checkpoint_path.exists() and not overwrite:
            raise FileExistsError(checkpoint_path)
        torch.save(
            {
                "schema": WORKER_SCHEMA,
                "route": args.route,
                "seed": args.seed,
                "model_state_dict": model.state_dict(),
                "architecture": architecture,
                "shared_graph_trunk": True,
                "posthoc_wall_projection": False,
                "output_clipping": False,
                "qualification_claim": False,
            },
            checkpoint_path,
        )
        if device.type == "cuda":
            torch.cuda.synchronize(device)
    except WorkerGuardError as error:
        attempt_status = "failed"
        worker_exit_status = "guard_terminated"
        failure_reason = str(error)
        failure_category = error.category
        exit_code = 2
        model_physical_pass = "unknown" if evaluation_completed else "not_evaluated"
    except Exception as error:  # retain a record even for an unexpected worker exception
        attempt_status = "failed"
        worker_exit_status = "exception"
        failure_reason = f"{type(error).__name__}: {error}"
        failure_category = "worker_exception"
        exit_code = 1
        model_physical_pass = "unknown" if evaluation_completed else "not_evaluated"
        evaluation_report["traceback"] = traceback.format_exc(limit=8)

    elapsed = time.monotonic() - started
    if device_report.get("device", "").startswith("cuda"):
        index = int(str(device_report["device"]).split(":", 1)[1])
        device_report["peak_memory_mb"] = float(torch.cuda.max_memory_allocated(index)) / (1024 * 1024)
    else:
        device_report["peak_memory_mb"] = None
    if attempt_status == "completed":
        failure_reason = "bounded diagnostic only; no physical qualification verdict emitted"
        model_physical_pass = "unknown"
    report = {
        "schema": ATTEMPT_REPORT_SCHEMA,
        "worker_schema": WORKER_SCHEMA,
        "execution_attempt_id": attempt_id,
        "logical_run_id": logical_run["logical_run_id"],
        "route": args.route,
        "seed": args.seed,
        "status": attempt_status,
        "worker_exit_status": worker_exit_status,
        "training_completed": training_completed,
        "evaluation_completed": evaluation_completed,
        "model_physical_pass": model_physical_pass,
        "failure_category": failure_category,
        "failure_reason": failure_reason,
        "elapsed_seconds": elapsed,
        "budget": {
            "max_steps": budget.max_steps,
            "max_frames": budget.max_frames,
            "max_particles": budget.max_particles,
            "max_seconds": budget.max_seconds,
            "max_gpu_memory_mb": budget.max_gpu_memory_mb,
            "max_neighbors": budget.max_neighbors,
        },
        "device": device_report,
        "data": data_report,
        "training": training_report,
        "evaluation": evaluation_report,
        "route_contract": {
            "raw_and_hybrid_share_graph_trunk": True,
            "hybrid_known_operator": "velocity*dt + 0.5*current_control_acceleration*dt^2",
            "future_state_used_as_input": False,
            "posthoc_wall_projection": False,
            "output_clipping": False,
            "qualification_claim": False,
        },
        "created_at_utc": utc_now(),
    }
    report_path = output_dir / "attempt-report.json"
    _write_json(report_path, report, overwrite=overwrite)
    artifacts = {
        "attempt_report": report_path.name,
        "failure_denominator": "failure-denominator.json",
        "study_manifest": str(study_path),
        "registry": str(registry_path),
        "checkpoint": "model.pt" if (output_dir / "model.pt").is_file() else None,
        "qualification_receipt_emitted": False,
    }
    attempt_record = create_attempt_record(
        logical_run_id=logical_run["logical_run_id"],
        route=args.route,
        seed=args.seed,
        physical_case_ids=physical_case_ids,
        execution_attempt_id=attempt_id,
        status=attempt_status,
        worker_exit_status=worker_exit_status,
        training_completed=training_completed,
        evaluation_completed=evaluation_completed,
        model_physical_pass=model_physical_pass,
        data_contract_sha256=data_contract_sha,
        model_contract_sha256=model_contract_sha,
        r2_evidence_sha256=r2_evidence_sha,
        gpu_index=device_report.get("gpu_index"),
        gpu_uuid=device_report.get("gpu_name"),
        cpu_cores=os.cpu_count(),
        elapsed_seconds=elapsed,
        failure_reason=failure_reason,
        artifacts=artifacts,
        finished_at_utc=utc_now(),
    )
    attempt_path = output_dir / "attempt.json"
    write_attempt_record(attempt_path, attempt_record, overwrite=overwrite)
    artifacts["attempt_record"] = attempt_path.name
    # The record on disk intentionally remains the exact validated record; the
    # denominator is derived from it rather than from an optimistic summary.
    denominator, denominator_path = _record_denominator(
        output_dir=output_dir,
        spec=spec,
        attempt_record=attempt_record,
        evaluation_rows=evaluation_rows,
        overwrite=overwrite,
    )
    return {
        "status": attempt_status,
        "exit_code": exit_code,
        "execution_attempt_id": attempt_id,
        "attempt_record": str(attempt_path),
        "attempt_report": str(report_path),
        "failure_denominator": str(denominator_path),
        "logical_outcome": next(
            row["outcome"]
            for row in denominator["logical_run_denominator"]["rows"]
            if row["logical_run_id"] == logical_run["logical_run_id"]
        ),
        "model_physical_pass": model_physical_pass,
        "training_completed": training_completed,
        "evaluation_completed": evaluation_completed,
    }


def _common_run_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--study", default=str(DEFAULT_STUDY))
    parser.add_argument("--route", choices=("raw", "hybrid"), required=True)
    parser.add_argument("--seed", type=int, choices=(17, 29, 43), required=True)
    parser.add_argument("--train-case-id", required=True)
    parser.add_argument("--eval-case-id", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--gpu-index", type=int)
    parser.add_argument("--allow-cpu", action="store_true")
    parser.add_argument("--max-steps", type=int, default=16)
    parser.add_argument("--max-frames", type=int, default=4)
    parser.add_argument("--max-particles", type=int, default=128)
    parser.add_argument("--max-seconds", type=float, default=120.0)
    parser.add_argument("--max-gpu-memory-mb", type=int, default=4096)
    parser.add_argument("--max-neighbors", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--verify-source-hashes", action="store_true")
    parser.add_argument("--attempt-id")
    parser.add_argument("--overwrite", action="store_true")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run", help="execute one bounded route/seed attempt")
    _common_run_arguments(run_parser)
    run_parser.set_defaults(handler=run_attempt)
    preflight_parser = sub.add_parser("preflight", help="validate one bounded attempt without training")
    _common_run_arguments(preflight_parser)
    preflight_parser.set_defaults(handler=None)
    return root


def preflight(args: argparse.Namespace) -> dict[str, Any]:
    budget = BoundedBudget(
        max_steps=args.max_steps,
        max_frames=args.max_frames,
        max_particles=args.max_particles,
        max_seconds=args.max_seconds,
        max_gpu_memory_mb=args.max_gpu_memory_mb,
        max_neighbors=args.max_neighbors,
    )
    budget.validate()
    study_path, manifest = load_study_manifest(args.study)
    spec = study_spec_from_manifest(manifest)
    registry_path, rows = load_registry_rows(manifest)
    if args.train_case_id not in rows or args.eval_case_id not in rows:
        raise WorkerGuardError("requested train/eval case is missing from canonical registry", category="missing_data")
    train_source = resolve_source_case(rows[args.train_case_id], expected_split="train")
    eval_source = resolve_source_case(rows[args.eval_case_id], expected_split=str(rows[args.eval_case_id].get("split")))
    device = _device_from_argument(args.device, allow_cpu=bool(args.allow_cpu))
    device_report = _device_preflight(device, budget, args.gpu_index)
    return {
        "status": "ready",
        "launch_allowed": True,
        "study": str(study_path),
        "registry": str(registry_path),
        "logical_run_count": len(spec.logical_runs),
        "evaluation_case_count": len(spec.evaluation_case_ids),
        "train_case": {"case_id": train_source.case_id, "split": train_source.split, "hdf5": str(train_source.hdf5_path)},
        "evaluation_case": {"case_id": eval_source.case_id, "split": eval_source.split, "hdf5": str(eval_source.hdf5_path)},
        "budget": budget.__dict__,
        "device": device_report,
        "shared_resume_mutation": False,
        "qualification_claim": False,
    }


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "preflight":
            result = preflight(args)
            exit_code = 0
        else:
            result = run_attempt(args)
            exit_code = int(result["exit_code"])
    except WorkerGuardError as error:
        result = {"status": "rejected", "category": error.category, "reason": str(error)}
        exit_code = 2
    except (B2RContractError, FileNotFoundError, ValueError) as error:
        result = {"status": "rejected", "category": "contract_rejected", "reason": str(error)}
        exit_code = 2
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
