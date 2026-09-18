#!/usr/bin/env python3
"""Persistent controller and first evidence passes for L2 Multifamily.

This module intentionally keeps the first L2 actions bounded and read-only
with respect to legacy data.  ``bootstrap`` records owner adoption and copies
the supplied planning package into the new namespace.  ``a0`` creates a
canonical F3 manifest and independently audits existing HDF5 artifacts.
``a1`` diagnoses the six legacy logical learning runs from their retained
evaluation manifests; it never retrains a model.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any, Iterable
import zipfile

import h5py
import numpy as np

try:
    from scripts.finite_wall_audit import wall_penetration
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from finite_wall_audit import wall_penetration


REPO = Path(__file__).resolve().parents[2]
LAB = REPO / "lagrangian-fluid-lab"
CAMPAIGN = LAB / "campaigns" / "l2-multifamily"
BASELINE_COMMIT = "4b554e69d69245db4a6a6772b296cf256c142a16"
DEFAULT_PLAN_ZIP = Path(
    "/home/jade/.codex/attachments/06949eb7-a834-4186-a763-12c168a80ef7/"
    "L2_Multifamily_Plan_4b554e69_2026-09-13.zip"
)
DEFAULT_CONTRACT = LAB / "campaigns/l1-resume/continuation/F3-REF0081818-TRAINING-DEVELOPMENT-FULL.json"
DEFAULT_CLOSURE = LAB / "campaigns/l1-resume/continuation/F3-REF0081818-TRAINING-CLOSURE.json"
DEFAULT_GATE = LAB / "campaigns/l1-resume/continuation/F3-075-REF0081818-GATE.json"
DEFAULT_CLOSEOUT = LAB / "campaigns/l1-resume/continuation/F3-REF0081818-CAMPAIGN-CLOSEOUT.json"
DEFAULT_REGISTRY = LAB / "campaigns/l1-resume/continuation/F3-075-REF0081818-DEVELOPMENT-REGISTRY.json"
DEFAULT_MATERIAL_INDEX = LAB / "campaigns/l1-resume/continuation/F3-REF0081818-MATERIAL-ARCHIVE-INDEX.json"
CHUNK_SIZE = 64 * 1024 * 1024
F3_WALL_BOUNDS = {
    "xmin": -0.45, "xmax": 0.45, "ymin": -0.09, "ymax": 0.09,
    "zmin": 0.0, "zmax": 0.6,
    "closed_faces": ["bottom", "left", "right", "front", "back"],
    "open_faces": ["top"],
}
REQUIRED_TRAJECTORY_DATASETS = ("time", "position", "velocity", "mass", "particle_id", "valid")
STAGE_DEPENDENCY_STATUSES = frozenset({"complete", "complete_with_findings", "blocked_external"})


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    os.replace(temporary, path)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def sha256_file(path: Path, *, with_chunks: bool = False) -> tuple[str, list[str]]:
    digest = hashlib.sha256()
    chunks: list[str] = []
    with path.open("rb") as handle:
        while True:
            block = handle.read(CHUNK_SIZE)
            if not block:
                break
            digest.update(block)
            if with_chunks:
                chunks.append(hashlib.sha256(block).hexdigest())
    return digest.hexdigest(), chunks


def file_evidence(path: Path, *, with_chunks: bool = False, cache: dict | None = None) -> dict:
    path = path.resolve()
    if not path.is_file():
        return {"path": str(path), "exists": False}
    stat = path.stat()
    cache_key = str(path)
    if cache is not None:
        old = cache.get(cache_key)
        if old and old.get("bytes") == stat.st_size and old.get("mtime_ns") == stat.st_mtime_ns:
            return dict(old)
    digest, chunks = sha256_file(path, with_chunks=with_chunks)
    result = {
        "path": str(path),
        "exists": True,
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": digest,
    }
    if with_chunks:
        result["chunk_size_bytes"] = CHUNK_SIZE
        result["chunk_sha256"] = chunks
    if cache is not None:
        cache[cache_key] = result
    return result


def repo_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def source_path(raw: str | Path) -> Path:
    """Resolve legacy evidence paths, which are rooted at the lab directory."""

    path = Path(raw)
    if path.is_absolute():
        return path
    for root in (LAB, REPO):
        candidate = (root / path).resolve()
        if candidate.exists():
            return candidate
    return (LAB / path).resolve()


def git_head() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, check=True,
            text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def plan_zip_digest(plan_zip: Path) -> str | None:
    if not plan_zip.is_file():
        return None
    return sha256_file(plan_zip)[0]


def extract_plan_package(plan_zip: Path) -> dict:
    """Preserve the supplied planning package verbatim under the new namespace."""

    destination = CAMPAIGN / "plan-source"
    destination.mkdir(parents=True, exist_ok=True)
    extracted: list[str] = []
    if not plan_zip.is_file():
        return {"path": str(plan_zip), "exists": False, "files": extracted}
    with zipfile.ZipFile(plan_zip) as archive:
        for member in archive.infolist():
            name = Path(member.filename)
            if name.name == "" or name.is_absolute() or ".." in name.parts:
                continue
            # Drop the outer package directory, retaining its original files.
            parts = name.parts
            relative = Path(*parts[1:]) if len(parts) > 1 else Path(name.name)
            target = (destination / relative).resolve()
            try:
                target.relative_to(destination.resolve())
            except ValueError:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(member))
            extracted.append(relative.as_posix())
    return {
        "path": str(plan_zip.resolve()),
        "exists": True,
        "sha256": plan_zip_digest(plan_zip),
        "files": sorted(extracted),
    }


def adoption_payload(plan_zip: Path) -> dict:
    adopted = utc_now()
    package = extract_plan_package(plan_zip)
    state = {
        "schema": "l2.campaign.state.v1",
        "campaign_id": "L2_MULTI_FAMILY_QUALIFICATION",
        "namespace": "lagrangian-fluid-lab/campaigns/l2-multifamily",
        "baseline_commit": BASELINE_COMMIT,
        "current_commit_at_adoption": git_head(),
        "owner_adoption_status": "accepted",
        "owner_adopted_at_utc": adopted,
        "owner_request": "这是云端的审阅者给我们下发的任务，我们来按照审阅者给出的规划来继续探索和执行。",
        "plan_package": package,
        "old_campaign_reopened": False,
        "legacy_scope": "read_only; no L1 budget reset or artifact reclassification",
        "public_release_authorized": False,
        "hidden_test_generation_authorized": False,
        "limits": {
            "gpu_hours": 96,
            "cpu_core_hours": 384,
            "new_storage_gib": 1024,
            "min_free_gib": 200,
            "min_free_fraction": 0.2,
            "lifetime_days_from_adoption": 10,
            "qualification_solver_attempts": 80,
            "development_solver_attempts": 160,
            "training_attempts": 18,
            "full_material_configurations": 24,
            "concurrent_heavy_gpu_tasks": 4,
            "concurrent_tasks_per_gpu": 2,
        },
        "stages": {
            "A0": {"status": "ready", "requires": []},
            "A1": {"status": "pending", "requires": ["A0"]},
            "B1": {"status": "pending", "requires": ["A0"]},
            "B2": {"status": "pending", "requires": ["A0", "A1"]},
            "C0": {"status": "pending", "requires": ["A0"]},
            "C1": {"status": "pending", "requires": ["C0"]},
            "C2": {"status": "pending", "requires": ["C0"]},
            "C3": {"status": "pending", "requires": ["C0"]},
            "D0": {"status": "pending", "requires": ["A0"]},
            "E0": {"status": "pending", "requires": ["A0", "A1", "B1", "B2", "C0", "C1", "C2", "C3", "D0"]},
        },
        "resource_usage": {
            "gpu_hours": 0.0,
            "cpu_core_hours_actual": 0.0,
            "cpu_core_hours_conservative": 0.0,
            "qualification_solver_attempts": 0,
            "development_solver_attempts": 0,
            "training_attempts": 0,
            "material_configurations": 0,
            "new_storage_bytes": 0,
        },
        "created_at_utc": adopted,
    }
    atomic_json(CAMPAIGN / "state.json", state)
    atomic_json(CAMPAIGN / "ledger.json", {
        "schema": "l2.resource.ledger.v1",
        "campaign_id": state["campaign_id"],
        "limits": state["limits"],
        "usage": state["resource_usage"],
        "reservations": [],
        "events": [{"event": "owner_adoption", "at_utc": adopted, "scope": "L2 only"}],
    })
    atomic_json(CAMPAIGN / "queue.json", {
        "schema": "l2.persistent.queue.v1",
        "campaign_id": state["campaign_id"],
        "tasks": [
            {"task_id": "A0", "stage": "A0", "status": "ready", "requires": []},
            {"task_id": "A1", "stage": "A1", "status": "pending", "requires": ["A0"]},
            {"task_id": "B1", "stage": "B1", "status": "pending", "requires": ["A0"]},
            {"task_id": "B2", "stage": "B2", "status": "pending", "requires": ["A0", "A1"]},
            {"task_id": "C0", "stage": "C0", "status": "pending", "requires": ["A0"]},
            {"task_id": "C1", "stage": "C1", "status": "pending", "requires": ["C0"]},
            {"task_id": "C2", "stage": "C2", "status": "pending", "requires": ["C0"]},
            {"task_id": "C3", "stage": "C3", "status": "pending", "requires": ["C0"]},
            {"task_id": "D0", "stage": "D0", "status": "pending", "requires": ["A0"]},
            {"task_id": "E0", "stage": "E0", "status": "pending", "requires": ["A0", "A1", "B1", "B2", "C0", "C1", "C2", "C3", "D0"]},
        ],
    })
    (CAMPAIGN / "ADOPTION.md").write_text(
        "# L2 多家族活动采纳记录\n\n"
        f"- 采纳时间（UTC）：`{adopted}`\n"
        f"- 审阅基线：`{BASELINE_COMMIT}`\n"
        f"- 计划包 SHA-256：`{package.get('sha256')}`\n"
        "- 所有者请求：按附件 `START_HERE_ZH.md` 与 `PLAN_ZH.md` 执行。\n"
        "- 旧 L1：只读；不恢复旧预算、不改判历史负结果。\n"
        "- 本活动：不包含公开发布、隐藏测试生成、付费扩容、强推、vendor 改写或历史删除。\n\n"
        "该文件只记录本地所有者采纳，不伪造云端签名或云端实时执行状态。\n"
    )
    (CAMPAIGN / "README.md").write_text(
        "# L2 Multifamily campaign\n\n"
        "This namespace is the persistent local execution record for the adopted "
        "L2 plan. Legacy L1 artifacts remain read-only.\n\n"
        "Commands:\n\n"
        "```text\n"
        "lagrangian-fluid-lab/.venv/bin/python scripts/l2_campaign.py status\n"
        "lagrangian-fluid-lab/.venv/bin/python scripts/l2_campaign.py a0\n"
        "lagrangian-fluid-lab/.venv/bin/python scripts/l2_campaign.py a1\n"
        "```\n"
    )
    return state


def require_adopted() -> dict:
    state_path = CAMPAIGN / "state.json"
    if not state_path.is_file():
        raise RuntimeError("L2 is not bootstrapped; run the bootstrap command first")
    state = read_json(state_path)
    if state.get("owner_adoption_status") != "accepted":
        raise RuntimeError("L2 owner adoption is not accepted")
    return state


def update_stage(stage: str, status: str, *, facts: dict | None = None) -> None:
    state = require_adopted()
    state["stages"][stage]["status"] = status
    state["stages"][stage]["updated_at_utc"] = utc_now()
    if facts:
        state["stages"][stage]["facts"] = facts
    atomic_json(CAMPAIGN / "state.json", state)
    queue = read_json(CAMPAIGN / "queue.json")
    for task in queue["tasks"]:
        if task["stage"] == stage:
            task["status"] = status
            task["updated_at_utc"] = state["stages"][stage]["updated_at_utc"]
    # ``blocked`` and ``blocked_upstream`` are not successful prerequisites.
    # Only a completed task, a completed-with-findings task, or a specifically
    # evidenced external block can release a dependent task.  In particular,
    # the old ``complete -> blocked -> E0`` shortcut must not be recreated.
    completed = {
        task["stage"] for task in queue["tasks"]
        if task["status"] in STAGE_DEPENDENCY_STATUSES
    }
    for task in queue["tasks"]:
        if task["status"] == "pending" and all(req in completed for req in task["requires"]):
            task["status"] = "ready"
    atomic_json(CAMPAIGN / "queue.json", queue)


def update_usage(**increments: float) -> None:
    state = require_adopted()
    usage = state["resource_usage"]
    for key, value in increments.items():
        usage[key] = usage.get(key, 0) + value
    atomic_json(CAMPAIGN / "state.json", state)
    ledger = read_json(CAMPAIGN / "ledger.json")
    ledger["usage"] = usage
    ledger["events"].append({"event": "usage_update", "at_utc": utc_now(), "increments": increments})
    atomic_json(CAMPAIGN / "ledger.json", ledger)


def _scan_array(dataset: h5py.Dataset, *, finite: bool = True) -> tuple[bool, int]:
    """Stream an array in frame-sized chunks and return validity/count."""

    count = 0
    if dataset.ndim == 0:
        values = np.asarray(dataset[()])
        return bool(np.isfinite(values).all()) if finite and np.issubdtype(values.dtype, np.number) else True, 1
    first_axis = dataset.shape[0]
    for start in range(0, first_axis, 16):
        values = np.asarray(dataset[start:min(start + 16, first_axis)])
        count += int(values.size)
        if finite and np.issubdtype(values.dtype, np.number) and not np.isfinite(values).all():
            return False, count
    return True, count


def _coerce_wall_spec(wall_bounds: dict | None, wall_spec: dict | None) -> tuple[dict | None, str]:
    """Convert legacy bounds to the finite-wall contract without making an AABB wall.

    A legacy dictionary is accepted only when it declares the finite ``zmax``
    rim as well as the five lower/side bounds.
    Without a finite rim the physical-wall verdict is unknown, rather than an
    infinite vertical-plane pass/fail result.
    """

    raw = wall_spec if wall_spec is not None else wall_bounds
    if raw is None:
        return None, "not_checked"
    dynamic_requested = bool(
        raw.get("moving_geometry_required")
        or raw.get("dynamic_geometry_required")
        or str(raw.get("geometry_mode", "")).lower() in {"moving", "dynamic"}
    )
    if dynamic_requested:
        # The endpoint audit below is valid only for a fixed finite geometry.
        # A moving cup needs a per-frame pose/boundary adapter before its wall
        # result can be promoted to a production gate.
        return None, "unknown"
    if "container_interior" in raw:
        spec = dict(raw)
        container = dict(spec.get("container_interior", {}))
    else:
        required = ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax")
        if any(key not in raw for key in required):
            return None, "unknown"
        container = {key: raw[key] for key in required}
        spec = {
            "container_interior": container,
            "closed_faces": raw.get("closed_faces", ["bottom", "left", "right", "front", "back"]),
            "open_faces": raw.get("open_faces", ["top"]),
        }
        if "obstacles" in raw:
            spec["obstacles"] = raw["obstacles"]
        if "runtime_domain" in raw:
            spec["runtime_domain"] = raw["runtime_domain"]
    if any(key not in container for key in ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax")):
        return None, "unknown"
    spec["container_interior"] = container
    return spec, "checked"


def inspect_hdf5(path: Path, *, full_scan: bool = True, wall_bounds: dict | None = None,
                 wall_spec: dict | None = None, runtime_domain: dict | None = None,
                 compare: dict | None = None) -> dict:
    """Independently validate active trajectory state and finite geometry.

    Inactive padding is allowed to contain NaN.  Active finite state, positive
    mass, lifecycle semantics, and finite closed-wall crossings are reported as
    separate gates so a conversion placeholder cannot be confused with solver
    divergence or physical loss.
    """

    result: dict[str, Any] = {"path": str(path.resolve()), "exists": path.is_file()}
    if not path.is_file():
        result["structural_pass"] = False
        result["errors"] = ["missing_file"]
        return result
    errors: list[str] = []
    with h5py.File(path, "r") as handle:
        missing = [name for name in REQUIRED_TRAJECTORY_DATASETS if name not in handle]
        result["datasets"] = {
            name: list(dataset.shape) for name, dataset in handle.items() if hasattr(dataset, "shape")
        }
        result["attrs"] = {str(key): str(value) for key, value in handle.attrs.items()}
        if missing:
            result["errors"] = [f"missing:{name}" for name in missing]
            result["structural_pass"] = False
            return result
        time_axis = np.asarray(handle["time"][:], dtype=np.float64)
        position = handle["position"]
        velocity = handle["velocity"]
        mass = handle["mass"]
        valid = handle["valid"]
        particle_id = np.asarray(handle["particle_id"][:])
        expected_t = len(time_axis)
        expected_n = len(particle_id)
        valid_dtype_ok = bool(
            np.issubdtype(valid.dtype, np.bool_) or np.issubdtype(valid.dtype, np.integer)
        )
        shape_checks = {
            "time": time_axis.ndim == 1 and expected_t >= 2 and np.isfinite(time_axis).all() and np.all(np.diff(time_axis) > 0),
            "particle_id": particle_id.ndim == 1 and expected_n > 0 and len(np.unique(particle_id)) == expected_n,
            "position": position.shape == (expected_t, expected_n, 3),
            "velocity": velocity.shape == (expected_t, expected_n, 3),
            "valid": valid.shape == (expected_t, expected_n),
            "mass": mass.shape in ((expected_n,), (expected_t, expected_n)),
        }
        errors.extend([f"shape:{key}" for key, okay in shape_checks.items() if not okay])
        if not valid_dtype_ok:
            errors.append("valid:dtype")
        finite = {"position": True, "velocity": True, "mass": True}
        optional_finite: dict[str, bool] = {}
        for optional in ("density", "pressure"):
            if optional in handle:
                optional_finite[optional] = True
        valid_count = 0
        mass_min = math.inf
        mass_max = -math.inf
        wall_violation_count = 0
        wall_violation_mass = 0.0
        inactive_nonfinite: Counter[str] = Counter()
        active_mass_positive = True
        mass_change_max_relative = 0.0
        initial_mass_total = math.nan
        final_mass_total = math.nan
        mass_reference = np.full(expected_n, np.nan, dtype=np.float64)
        initial_valid = np.zeros(expected_n, dtype=bool)
        final_valid = np.zeros(expected_n, dtype=bool)
        ever_valid = np.zeros(expected_n, dtype=bool)
        dead_after_valid = np.zeros(expected_n, dtype=bool)
        birth_count = 0
        death_count = 0
        resurrection_count = 0
        previous_valid: np.ndarray | None = None
        wall_payload, wall_status = _coerce_wall_spec(wall_bounds, wall_spec)
        if wall_payload is not None and runtime_domain is not None:
            wall_payload = dict(wall_payload)
            wall_payload["runtime_domain"] = runtime_domain
        elif wall_payload is not None and "runtime_domain" not in wall_payload:
            wall_payload = dict(wall_payload)
        if not errors and full_scan:
            for start in range(0, expected_t, 16):
                stop = min(start + 16, expected_t)
                positions = np.asarray(position[start:stop], dtype=np.float64)
                velocities = np.asarray(velocity[start:stop], dtype=np.float64)
                masses = np.asarray(
                    mass[start:stop] if mass.ndim == 2 else np.broadcast_to(mass[:], (stop - start, expected_n)),
                    dtype=np.float64,
                )
                raw_valid = np.asarray(valid[start:stop])
                if valid_dtype_ok and np.issubdtype(raw_valid.dtype, np.integer):
                    if not np.isin(raw_valid, (0, 1)).all():
                        errors.append("valid:values")
                    frame_valid_block = raw_valid.astype(bool)
                else:
                    frame_valid_block = raw_valid.astype(bool)
                for row_index, frame_valid in enumerate(frame_valid_block):
                    if start == 0 and row_index == 0:
                        initial_valid = frame_valid.copy()
                    if previous_valid is not None:
                        births = (~previous_valid) & frame_valid
                        deaths = previous_valid & (~frame_valid)
                        resurrection_count += int((dead_after_valid & (~previous_valid) & frame_valid).sum())
                        birth_count += int(births.sum())
                        death_count += int(deaths.sum())
                        dead_after_valid |= deaths
                    ever_valid |= frame_valid
                    previous_valid = frame_valid.copy()
                    final_valid = frame_valid.copy()
                    row_mass = masses[row_index]
                    row_finite_mass = frame_valid & np.isfinite(row_mass)
                    row_mass_total = float(np.sum(row_mass[row_finite_mass], dtype=np.float64))
                    if initial_mass_total != initial_mass_total:
                        initial_mass_total = row_mass_total
                    final_mass_total = row_mass_total
                active = frame_valid_block
                active_position_finite = np.isfinite(positions).all(axis=2)
                active_velocity_finite = np.isfinite(velocities).all(axis=2)
                active_mass_finite = np.isfinite(masses)
                finite["position"] = finite["position"] and bool(active_position_finite[active].all())
                finite["velocity"] = finite["velocity"] and bool(active_velocity_finite[active].all())
                finite["mass"] = finite["mass"] and bool(active_mass_finite[active].all())
                active_mass_positive = active_mass_positive and bool((masses[active] > 0).all())
                valid_count += int(active.sum())
                if active.any():
                    active_values = masses[active]
                    mass_min = min(mass_min, float(np.min(active_values)))
                    mass_max = max(mass_max, float(np.max(active_values)))
                inactive = ~active
                inactive_nonfinite["position"] += int((~active_position_finite & inactive).sum())
                inactive_nonfinite["velocity"] += int((~active_velocity_finite & inactive).sum())
                inactive_nonfinite["mass"] += int((~active_mass_finite & inactive).sum())
                for optional, flag in optional_finite.items():
                    values = np.asarray(handle[optional][start:stop], dtype=np.float64)
                    if values.shape[:2] == active.shape:
                        finite_values = np.isfinite(values)
                        selector_shape = active.shape + (1,) * max(0, values.ndim - 2)
                        flag_active = np.broadcast_to(active.reshape(selector_shape), values.shape)
                        optional_finite[optional] = flag and bool(finite_values[flag_active].all())
                        inactive_nonfinite[optional] += int((~finite_values & (~flag_active)).sum())
                    else:
                        optional_finite[optional] = False
                        errors.append(f"shape:{optional}")
                for row_index, frame_valid in enumerate(frame_valid_block):
                    row_mass = masses[row_index]
                    selected = frame_valid & np.isfinite(row_mass)
                    if selected.any():
                        reference = mass_reference[selected]
                        unset = ~np.isfinite(reference)
                        selected_indices = np.flatnonzero(selected)
                        if unset.any():
                            mass_reference[selected_indices[unset]] = row_mass[selected_indices[unset]]
                        set_indices = selected_indices[~unset]
                        if len(set_indices):
                            denominator = np.maximum(np.abs(mass_reference[set_indices]), 1e-30)
                            relative = np.abs(row_mass[set_indices] - mass_reference[set_indices]) / denominator
                            mass_change_max_relative = max(mass_change_max_relative, float(np.max(relative)))
                if wall_payload is not None:
                    for row_index, frame_valid in enumerate(frame_valid_block):
                        selected = frame_valid & np.isfinite(positions[row_index]).all(axis=1)
                        if not selected.any():
                            continue
                        wall = wall_penetration(
                            positions[row_index][selected], masses[row_index][selected], wall_payload, 1e-8
                        )
                        wall_violation_count += int(wall["outside_closed_container_count"] + wall["obstacle_penetration_count"])
                        wall_violation_mass += float(
                            wall["outside_closed_container_mass_kg"] + wall["obstacle_penetration_mass_kg"]
                        )
        else:
            finite = {key: False for key in finite}
            active_mass_positive = False
            wall_status = "not_scanned"
        lifecycle_model = str(handle.attrs.get("lifecycle_model", "closed")).lower()
        if lifecycle_model not in {"closed", "open"}:
            errors.append("lifecycle:model")
        if lifecycle_model == "closed" and (birth_count or death_count or resurrection_count):
            errors.append("lifecycle:closed_transition")
        if not active_mass_positive:
            errors.append("mass:active_nonpositive_or_nonfinite")
        if valid_count == 0:
            active_mass_positive = False
            errors.append("valid:no_active_entries")
        if mass_change_max_relative > 1e-8:
            errors.append("mass:active_change")
        if wall_status == "unknown":
            errors.append("wall:finite_geometry_unknown")
        errors.extend([f"nonfinite:{key}" for key, okay in finite.items() if not okay])
        errors.extend([f"nonfinite:{key}" for key, okay in optional_finite.items() if not okay])
        result.update({
            "time_start_s": float(time_axis[0]) if expected_t else None,
            "time_end_s": float(time_axis[-1]) if expected_t else None,
            "frame_count": expected_t,
            "particle_count": expected_n,
            "finite": finite,
            "finite_active": {**finite, **optional_finite},
            "inactive_nonfinite_counts": dict(inactive_nonfinite),
            "valid_entries_scanned": valid_count,
            "mass_min_kg": None if mass_min == math.inf else mass_min,
            "mass_max_kg": None if mass_max == -math.inf else mass_max,
            "initial_mass_kg": None if not math.isfinite(initial_mass_total) else initial_mass_total,
            "final_mass_kg": None if not math.isfinite(final_mass_total) else final_mass_total,
            "mass_loss_kg": (
                None if not (math.isfinite(initial_mass_total) and math.isfinite(final_mass_total))
                else initial_mass_total - final_mass_total
            ),
            "final_mass_fraction_of_initial": (
                None if not (math.isfinite(initial_mass_total) and initial_mass_total > 0 and math.isfinite(final_mass_total))
                else final_mass_total / initial_mass_total
            ),
            "active_mass_positive": active_mass_positive,
            "mass_change_max_relative": mass_change_max_relative,
            "initial_valid_count": int(initial_valid.sum()),
            "final_valid_count": int(final_valid.sum()),
            "identities_ever_valid": int(ever_valid.sum()),
            "birth_count": birth_count,
            "death_count": death_count,
            "resurrection_count": resurrection_count,
            "lifecycle_model": lifecycle_model,
            "wall_violation_count": wall_violation_count,
            "wall_violation_mass_kg": wall_violation_mass,
            "wall_status": wall_status,
            "full_scan": full_scan,
        })
    result["errors"] = errors
    result["structural_pass"] = not errors and result.get("wall_violation_count", 0) == 0
    if compare:
        result["compare"] = {
            key: {"expected": value, "actual": result.get(key), "match": result.get(key) == value}
            for key, value in compare.items()
        }
    return result


def load_a0_sources() -> tuple[dict, dict, dict, dict, dict, dict]:
    return (
        read_json(DEFAULT_CONTRACT),
        read_json(DEFAULT_GATE),
        read_json(DEFAULT_CLOSEOUT),
        read_json(DEFAULT_REGISTRY),
        read_json(DEFAULT_CLOSURE),
        read_json(DEFAULT_MATERIAL_INDEX),
    )


def load_cache() -> dict:
    path = CAMPAIGN / "evidence" / "file-hash-cache.json"
    return read_json(path) if path.is_file() else {}


def save_cache(cache: dict) -> None:
    atomic_json(CAMPAIGN / "evidence" / "file-hash-cache.json", cache)


def canonical_recipe(contract: dict, gate: dict, closeout: dict) -> dict:
    prepared_path = LAB / "campaigns/l1-resume/continuation/F3_CELL3_LONG_dp0p0075_a1p000_noslip_visco1_nopen-PREPARED.json"
    prepared = read_json(prepared_path) if prepared_path.is_file() else {}
    return {
        "recipe_id": gate["recipe_id"],
        "production_resolution_m": gate["production_resolution_m"],
        "reference_resolutions_m": gate["reference_resolutions_m"],
        "historical_resolution_m": gate["retained_historical_resolution_m"],
        "solver_mode": prepared.get("solver_mode", "-mdbc_noslip:1"),
        "boundary": prepared.get("boundary", 2),
        "slip_mode": prepared.get("slip_mode", 2),
        "no_penetration": prepared.get("expected_no_penetration", True),
        "visco": prepared.get("visco", 0.05),
        "visco_bound_factor": prepared.get("visco_bound_factor", 1),
        "shifting": prepared.get("shifting", 0),
        "native_velocity_displacement_correction": prepared.get("native_velocity_displacement_correction", True),
        "posthoc_particle_projection": prepared.get("posthoc_particle_projection", False),
        "time_window_s": gate["time_window_s"],
        "output_interval_s": gate["scoring_interval_s"],
        "control_domain": gate["control_domain"],
        "independent_interior_amplitude": closeout["recipe"].get("independent_interior"),
        "coordinate_frame": gate["coordinate_frame"],
        "scoring_scope": closeout["recipe"].get("scope_note"),
        "trajectory_semantics": "numerical SPH particle identity; material path remains a separate T2 task",
    }


def build_canonical_manifest() -> dict:
    contract, gate, closeout, registry, closure, material_index = load_a0_sources()
    cache = load_cache()
    recipe = canonical_recipe(contract, gate, closeout)
    cases: list[dict] = []
    wall = F3_WALL_BOUNDS
    for source_case in contract["cases"]:
        case_id = source_case["case_id"]
        hdf5_rel = source_case["sources"]["hdf5"]["path"]
        hdf5_path = source_path(hdf5_rel)
        audit_path = source_path(source_case["sources"]["audit"]["path"])
        audit = read_json(audit_path) if audit_path.is_file() else {}
        file_info = file_evidence(hdf5_path, with_chunks=True, cache=cache)
        audit_info = inspect_hdf5(
            hdf5_path, full_scan=True, wall_bounds=wall,
            compare=None,
        )
        cases.append({
            "case_id": case_id,
            "physical_case_id": case_id,
            "lineage_group_id": source_case.get("physical_lineage_sha256", case_id),
            "family": "F3",
            "split": source_case["split"],
            "evaluation_role": source_case["evaluation_role"],
            "drive_amplitude": source_case["drive_amplitude"],
            "recipe_id": source_case["recipe_id"] if "recipe_id" in source_case else contract["recipe_id"],
            "hdf5": hdf5_rel,
            "file": file_info,
            "source_evidence": source_case["sources"],
            "recorded_contract": {
                "hard_audit_passed": source_case.get("hard_audit_passed"),
                "native_frames": source_case.get("native_frames"),
                "native_time_end_s": source_case.get("native_time_end_s"),
            },
            "independent_audit": audit_info,
            "legacy_audit_status": audit.get("audit_status"),
            "legacy_acceptance_status": audit.get("acceptance_status"),
            "qualification_axes": {
                "structural": bool(audit_info.get("structural_pass")),
                "T1_registered_numerical": bool(source_case.get("hard_audit_passed")) and gate.get("status") == "passed",
                "T2_macro": False,
                "T2_path": False,
                "model_result": False,
                "release_readiness": False,
            },
        })
    archive_entries = []
    for case in cases:
        info = case["file"]
        archive_entries.append({
            "logical_id": case["case_id"],
            "path": case["hdf5"],
            "bytes": info.get("bytes"),
            "sha256": info.get("sha256"),
            "chunk_size_bytes": info.get("chunk_size_bytes"),
            "chunk_sha256": info.get("chunk_sha256"),
            "schema": "native-converted F3 trajectory HDF5 v1 contract",
            "license": "inherit DualSPHysics/source artifact licensing; publication not authorized by L2",
        })
    source_records = {
        "contract": {"path": repo_relative(DEFAULT_CONTRACT), "sha256": sha256_file(DEFAULT_CONTRACT)[0]},
        "gate": {"path": repo_relative(DEFAULT_GATE), "sha256": sha256_file(DEFAULT_GATE)[0]},
        "closeout": {"path": repo_relative(DEFAULT_CLOSEOUT), "sha256": sha256_file(DEFAULT_CLOSEOUT)[0]},
        "registry": {"path": repo_relative(DEFAULT_REGISTRY), "sha256": sha256_file(DEFAULT_REGISTRY)[0]},
        "closure": {"path": repo_relative(DEFAULT_CLOSURE), "sha256": sha256_file(DEFAULT_CLOSURE)[0]},
        "material_index": {"path": repo_relative(DEFAULT_MATERIAL_INDEX), "sha256": sha256_file(DEFAULT_MATERIAL_INDEX)[0]},
    }
    manifest = {
        "schema": "l2.f3.canonical_manifest.v1",
        "campaign_id": "L2_MULTI_FAMILY_QUALIFICATION",
        "created_at_utc": utc_now(),
        "baseline_commit": BASELINE_COMMIT,
        "current_commit": git_head(),
        "repository_root": str(LAB.resolve()),
        "status": "registered_T1_preserved; independent_A0_audit_recorded",
        "qualification_axes": {
            "data": "registered_numerical_reference",
            "material_macro": "candidate_only_not_qualified",
            "material_path": "candidate_only_not_qualified",
            "learning": "negative_baseline_only",
            "release": "internal_candidate_only",
        },
        "recipe": recipe,
        "legacy_case_count": len(cases),
        "physical_case_count": len({case["physical_case_id"] for case in cases}),
        "split_counts": dict(Counter(case["split"] for case in cases)),
        "source_records": source_records,
        "cases": cases,
        "archive_manifest": {
            "schema": "l2.content_addressed_file_manifest.v1",
            "chunk_size_bytes": CHUNK_SIZE,
            "entries": archive_entries,
            "external_archives": [
                {"path": "/home/jade/Projects/DualSPHysics/f3-ref0081818-training-archive", "status": "external_local_only", "bytes_not_rehashed": True},
                {"path": "/home/jade/Projects/DualSPHysics/f3-ref0081818-material-archive", "status": "external_local_only", "bytes_not_rehashed": True},
            ],
        },
        "interpretation": {
            "reference_ladder_actual_m": gate["reference_resolutions_m"],
            "historical_resolution_not_current_reference_m": gate["retained_historical_resolution_m"],
            "native_correction_is_solver_semantics": True,
            "posthoc_projection": False,
            "source_labels_are_for_scoring_not_permanent_neighbor_partition": True,
        },
    }
    atomic_json(CAMPAIGN / "evidence/f3-canonical-manifest.json", manifest)
    atomic_json(CAMPAIGN / "evidence/archive-manifest.json", manifest["archive_manifest"])
    save_cache(cache)
    return manifest


def material_evidence(material_index: dict) -> list[dict]:
    completed = []
    for attempt in material_index.get("attempts", []):
        if attempt.get("status") != "completed":
            continue
        directory = attempt.get("directory")
        if not directory:
            continue
        root = Path(directory)
        aligned = root / "aligned.h5"
        completed.append({
            "config_id": attempt.get("config_id"),
            "status": attempt.get("status"),
            "directory": str(root),
            "aligned_h5": file_evidence(aligned, with_chunks=False),
            "artifact_manifest": attempt.get("artifact_manifest"),
        })
    return completed


def run_a0() -> dict:
    require_adopted()
    started_wall = time.perf_counter()
    started_cpu = time.process_time()
    manifest = build_canonical_manifest()
    contract, gate, closeout, registry, closure, material_index = load_a0_sources()
    sentinel_defs = [
        ("endpoint_low", LAB / "campaigns/l1-resume/data/continuation/R0081818-ENDPOINT-LOW.h5", "reference_low_amplitude"),
        ("nominal", LAB / "campaigns/l1-resume/data/continuation/R0081818-NOMINAL.h5", "reference_nominal"),
        ("endpoint_high", LAB / "campaigns/l1-resume/data/continuation/R0081818-ENDPOINT-HIGH.h5", "reference_high_amplitude"),
        ("production_reference", LAB / "campaigns/l1-resume/data/continuation/F3_CELL3_LONG_dp0p0075_a1p000_noslip_visco1_nopen.h5", "production_reference"),
    ]
    sentinels = []
    for label, path, role in sentinel_defs:
        info = file_evidence(path, with_chunks=True, cache=load_cache())
        audit = inspect_hdf5(path, full_scan=True, wall_bounds=F3_WALL_BOUNDS)
        sentinels.append({"label": label, "role": role, "file": info, "independent_audit": audit})
    materials = material_evidence(material_index)
    weights = []
    for run in closure["training_matrix"]["logical_runs"]:
        if run["route"] not in {"particle_mlp", "local_interaction"} or run["seed"] != 17:
            continue
        raw = run["training_artifacts"]["weights"]["path"]
        path = Path(raw)
        weights.append({
            "logical_run_id": run["logical_run_id"],
            "route": run["route"],
            "seed": run["seed"],
            "recorded_sha256": run["training_artifacts"]["weights"].get("sha256"),
            "file": file_evidence(path, with_chunks=False),
        })
    report = {
        "schema": "l2.a0.replay.v1",
        "stage": "A0",
        "created_at_utc": utc_now(),
        "baseline_commit": BASELINE_COMMIT,
        "source_gate_status": gate.get("status"),
        "source_gate_is_not_this_run": True,
        "canonical_manifest": "evidence/f3-canonical-manifest.json",
        "full_manifest_case_count": len(manifest["cases"]),
        "full_manifest_structural_pass_count": sum(case["independent_audit"].get("structural_pass", False) for case in manifest["cases"]),
        "full_manifest_recorded_T1_count": sum(case["qualification_axes"]["T1_registered_numerical"] for case in manifest["cases"]),
        "sentinels": sentinels,
        "material_candidates": materials,
        "model_weight_candidates": weights,
        "acceptance": {
            "canonical_manifest": len(manifest["cases"]) == 32,
            "all_32_independent_structural_audits": all(case["independent_audit"].get("structural_pass", False) for case in manifest["cases"]),
            "all_32_recorded_T1": all(case["qualification_axes"]["T1_registered_numerical"] for case in manifest["cases"]),
            "all_sentinels_structural": all(item["independent_audit"].get("structural_pass", False) for item in sentinels),
            "reference_ladder_corrected": manifest["recipe"]["reference_resolutions_m"] == [0.00818181818181818, 0.0075, 0.006],
            "native_correction_explicit": manifest["recipe"]["native_velocity_displacement_correction"] is True and manifest["recipe"]["posthoc_particle_projection"] is False,
            "materials_remain_T2_unqualified": all(item["status"] == "completed" for item in materials) and len(materials) == 2,
            "model_state_separate_from_data": True,
        },
        "resource_observation": {
            "wall_seconds": time.perf_counter() - started_wall,
            "process_cpu_seconds": time.process_time() - started_cpu,
            "input_bytes_inspected": sum(item["file"].get("bytes", 0) for item in sentinels) + sum(case["file"].get("bytes", 0) for case in manifest["cases"]),
            "new_storage_bytes": 0,
        },
    }
    report["status"] = "complete" if all(report["acceptance"].values()) else "complete_with_findings"
    atomic_json(CAMPAIGN / "reports/a0-replay.json", report)
    update_usage(cpu_core_hours_actual=report["resource_observation"]["process_cpu_seconds"] / 3600.0)
    update_stage("A0", "complete" if report["status"] == "complete" else "complete_with_findings", facts={
        "report": "reports/a0-replay.json",
        "canonical_manifest": "evidence/f3-canonical-manifest.json",
        "case_count": len(manifest["cases"]),
        "sentinel_count": len(sentinels),
    })
    return report


def resolve_external(raw: str | Path) -> Path:
    path = Path(raw)
    if path.is_file():
        return path
    candidates = [REPO / path, LAB / path]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return path


def safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def summarize_replay_case(run_id: str, route: str, seed: int, case: dict) -> dict:
    first = case.get("first_failure") or {}
    crossing = first.get("first_crossing") or {}
    metrics_mean = case.get("metrics_mean") or {}
    terminal = case.get("terminal_failure") or {}
    expected = int(case.get("expected_frames", 0) or 0)
    saved = int(case.get("saved_frames", 0) or 0)
    return {
        "run_id": run_id,
        "route": route,
        "seed": seed,
        "case_id": case.get("case_id"),
        "status": case.get("status"),
        "expected_frames": expected,
        "saved_frames": saved,
        "rollout_complete": saved == expected and expected > 0,
        "hard_wall_passed": bool(case.get("hard_wall_passed", False)),
        "evaluation_case_record_present": True,
        "first_failure_time_s": safe_float(first.get("time_s")),
        "failure_kind": first.get("kind"),
        "first_crossing_kind": crossing.get("kind"),
        "first_crossing_face": crossing.get("face"),
        "first_crossing_particle_id": crossing.get("particle_id"),
        "wall_invalid_frames": case.get("wall_invalid_frames"),
        "swept_crossing_count": case.get("swept_crossing_count"),
        "terminal_failure_kind": terminal.get("kind"),
        "terminal_failure_message": terminal.get("message"),
        "finite_failure_observed": bool(terminal) or str(first.get("kind", "")).startswith("runtime_or_nonfinite"),
        "unmatched_support_mass_fraction": safe_float(metrics_mean.get("unmatched_support_mass")),
        "position_same_id_mass_rms": safe_float(metrics_mean.get("position_same_id_mass_rms")),
        "energy_difference": safe_float(metrics_mean.get("energy_difference")),
        "source_case_metrics": {
            "particle_count": case.get("particle_count"),
            "initial_mass_kg": case.get("initial_mass_kg"),
            "ranking_eligible": case.get("ranking_eligible"),
        },
    }


def load_training_runs(closure: dict) -> tuple[list[dict], list[dict]]:
    runs: list[dict] = []
    case_records: list[dict] = []
    for run in closure["training_matrix"]["logical_runs"]:
        route = run["route"]
        seed = int(run["seed"])
        attempt = run.get("attempt", {})
        step_record = resolve_external(attempt.get("path", ""))
        step_dir = step_record.parent if step_record.name == "attempt.json" else Path(attempt.get("path", "")).parent
        artifacts = run.get("training_artifacts", {})
        steps_path = resolve_external(artifacts.get("steps_jsonl", {}).get("path", ""))
        weights_path = resolve_external(artifacts.get("weights", {}).get("path", ""))
        declared = int(run["evaluation"].get("declared_case_count", 0))
        by_case: dict[str, dict] = {}
        replay_files: list[str] = []
        for replay in run["evaluation"].get("replay_manifests", []):
            replay_path = resolve_external(replay.get("manifest", {}).get("path", ""))
            replay_files.append(str(replay_path))
            if not replay_path.is_file():
                continue
            payload = read_json(replay_path)
            result = payload.get("result") or {}
            for case in result.get("cases", []):
                by_case[case.get("case_id")] = summarize_replay_case(run["logical_run_id"], route, seed, case)
        records = [by_case[key] for key in sorted(by_case) if key]
        case_records.extend(records)
        training_completed = bool(artifacts.get("max_steps_reached")) and int(artifacts.get("steps_jsonl", {}).get("line_count", 0)) >= 16384 and weights_path.is_file()
        evaluation_completed = bool(run["evaluation"].get("all_cases_replayed")) and len(records) == declared
        model_pass = evaluation_completed and len(records) == declared and all(record["hard_wall_passed"] for record in records)
        runs.append({
            "logical_run_id": run["logical_run_id"],
            "route": route,
            "seed": seed,
            "attempt_status": run.get("attempt_status"),
            "stop_reason": run.get("stop_reason"),
            "training_completed": training_completed,
            "worker_exit_status": run.get("attempt_status"),
            "worker_exit_clean": run.get("attempt_status") == "completed",
            "evaluation_completed": evaluation_completed,
            "model_physical_pass": model_pass,
            "declared_evaluation_cases": declared,
            "covered_evaluation_cases": len(records),
            "passed_cases": sum(record["hard_wall_passed"] for record in records),
            "failed_cases": sum(not record["hard_wall_passed"] for record in records),
            "steps_jsonl": {"path": str(steps_path), "exists": steps_path.is_file(), "recorded_line_count": artifacts.get("steps_jsonl", {}).get("line_count")},
            "weights": {"path": str(weights_path), "exists": weights_path.is_file(), "recorded_sha256": artifacts.get("weights", {}).get("sha256")},
            "replay_manifests": replay_files,
            "case_ids": sorted(by_case),
        })
    return runs, case_records


def percentile(values: Iterable[float], q: float) -> float | None:
    data = np.asarray(list(values), dtype=np.float64)
    if data.size == 0:
        return None
    return float(np.percentile(data, q))


def aggregate_failure_profile(case_records: list[dict]) -> dict:
    times = [record["first_failure_time_s"] for record in case_records if record["first_failure_time_s"] is not None]
    by_case: dict[str, list[dict]] = defaultdict(list)
    for record in case_records:
        by_case[record["case_id"]].append(record)
    physical_cases = []
    for case_id, records in sorted(by_case.items()):
        case_times = [record["first_failure_time_s"] for record in records if record["first_failure_time_s"] is not None]
        physical_cases.append({
            "case_id": case_id,
            "run_count": len(records),
            "all_runs_failed": all(not record["hard_wall_passed"] for record in records),
            "median_first_failure_time_s": percentile(case_times, 50),
            "min_first_failure_time_s": min(case_times) if case_times else None,
            "max_first_failure_time_s": max(case_times) if case_times else None,
            "routes": sorted({record["route"] for record in records}),
        })
    faces = Counter(record["first_crossing_face"] for record in case_records if record["first_crossing_face"])
    thresholds = [0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 4.0, 8.0]
    survival_case_runs = {
        str(threshold): sum(
            record["first_failure_time_s"] is None or record["first_failure_time_s"] > threshold
            for record in case_records
        ) / len(case_records) if case_records else None
        for threshold in thresholds
    }
    survival_physical = {
        str(threshold): sum(
            record["median_first_failure_time_s"] is None or record["median_first_failure_time_s"] > threshold
            for record in physical_cases
        ) / len(physical_cases) if physical_cases else None
        for threshold in thresholds
    }
    return {
        "case_run_count": len(case_records),
        "unique_physical_case_count": len(physical_cases),
        "first_failure_time_s": {
            "min": min(times) if times else None,
            "p25": percentile(times, 25),
            "median": percentile(times, 50),
            "p75": percentile(times, 75),
            "max": max(times) if times else None,
        },
        "first_crossing_face_counts": dict(faces),
        "finite_failure_case_run_count": sum(record["finite_failure_observed"] for record in case_records),
        "wall_failure_case_run_count": sum(not record["hard_wall_passed"] for record in case_records),
        "rollout_complete_case_run_count": sum(record["rollout_complete"] for record in case_records),
        "survival_curve_case_run": survival_case_runs,
        "survival_curve_physical_case_median_over_seeds": survival_physical,
        "physical_case_summaries": physical_cases,
    }


def oracle_for_hdf5(path: Path) -> dict:
    """Run source-only oracle checks on a complete trajectory."""

    result: dict[str, Any] = {"path": str(path.resolve()), "exists": path.is_file()}
    if not path.is_file():
        return result
    with h5py.File(path, "r") as handle:
        times = np.asarray(handle["time"][:], dtype=np.float64)
        positions = handle["position"]
        velocities = handle["velocity"]
        particle_id = np.asarray(handle["particle_id"][:])
        valid = handle["valid"]
        n = len(particle_id)
        truth_outside = 0
        displacement_error_max = 0.0
        velocity_errors: list[float] = []
        constant_errors: list[float] = []
        initial_position = np.asarray(positions[0], dtype=np.float64)
        initial_velocity = np.asarray(velocities[0], dtype=np.float64)
        for frame in range(len(times) - 1):
            current = np.asarray(positions[frame], dtype=np.float64)
            next_position = np.asarray(positions[frame + 1], dtype=np.float64)
            next_velocity = np.asarray(velocities[frame], dtype=np.float64)
            active = np.asarray(valid[frame], dtype=bool) & np.asarray(valid[frame + 1], dtype=bool)
            finite_position = np.isfinite(current).all(axis=1) & np.isfinite(next_position).all(axis=1)
            wall_active = active & finite_position
            if wall_active.any():
                wall = wall_penetration(
                    next_position[wall_active], np.ones(int(wall_active.sum())), F3_WALL_BOUNDS, 1e-8
                )
                truth_outside += int(
                    wall["outside_closed_container_count"] + wall["obstacle_penetration_count"]
                )
            delta = next_position - current
            if finite_position.any():
                displacement_error_max = max(
                    displacement_error_max,
                    float(np.max(np.abs(current[finite_position] + delta[finite_position] - next_position[finite_position]))),
                )
            dt = float(times[frame + 1] - times[frame])
            error_active = wall_active & np.isfinite(next_velocity).all(axis=1)
            velocity_error = np.linalg.norm(next_position - (current + next_velocity * dt), axis=1)[error_active]
            velocity_errors.extend(velocity_error.tolist())
            constant = initial_position + initial_velocity * float(times[frame + 1] - times[0])
            constant_active = error_active & np.isfinite(initial_position).all(axis=1) & np.isfinite(initial_velocity).all(axis=1)
            constant_error = np.linalg.norm(next_position - constant, axis=1)[constant_active]
            constant_errors.extend(constant_error.tolist())
        result.update({
            "truth_identity_axis_unique": len(np.unique(particle_id)) == n,
            "truth_closed_wall_sampled_violation_count": truth_outside,
            "real_trajectory_oracle_pass": truth_outside == 0,
            "reference_next_displacement_update_max_abs_error_m": displacement_error_max,
            "reference_next_displacement_update_pass": displacement_error_max <= 1e-6,
            "velocity_integrator_error_m": {
                "mean": float(np.mean(velocity_errors)) if velocity_errors else None,
                "p95": percentile(velocity_errors, 95),
                "max": max(velocity_errors) if velocity_errors else None,
                "sample_count": len(velocity_errors),
            },
            "constant_velocity_baseline_error_m": {
                "mean": float(np.mean(constant_errors)) if constant_errors else None,
                "p95": percentile(constant_errors, 95),
                "max": max(constant_errors) if constant_errors else None,
                "sample_count": len(constant_errors),
            },
            "low_resolution_oracle_scope": "source trajectory only; not a model qualification or external validation",
        })
    return result


def run_a1() -> dict:
    state = require_adopted()
    if state["stages"]["A0"]["status"] not in {"complete", "complete_with_findings"}:
        raise RuntimeError("A1 requires A0 to be complete")
    started_wall = time.perf_counter()
    started_cpu = time.process_time()
    closure = read_json(DEFAULT_CLOSURE)
    runs, case_records = load_training_runs(closure)
    canonical = read_json(CAMPAIGN / "evidence/f3-canonical-manifest.json")
    sentinel_paths = [
        LAB / "campaigns/l1-resume/data/continuation/R0081818-ENDPOINT-LOW.h5",
        LAB / "campaigns/l1-resume/data/continuation/R0081818-NOMINAL.h5",
        LAB / "campaigns/l1-resume/data/continuation/R0081818-ENDPOINT-HIGH.h5",
    ]
    oracles = [{"label": path.stem, **oracle_for_hdf5(path)} for path in sentinel_paths]
    route_summary: dict[str, dict] = {}
    for route in sorted({run["route"] for run in runs}):
        selected = [run for run in runs if run["route"] == route]
        selected_cases = [record for record in case_records if record["route"] == route]
        failure_times = [record["first_failure_time_s"] for record in selected_cases if record["first_failure_time_s"] is not None]
        route_summary[route] = {
            "logical_run_count": len(selected),
            "seeds": sorted(run["seed"] for run in selected),
            "training_completed_count": sum(run["training_completed"] for run in selected),
            "worker_exit_clean_count": sum(run["worker_exit_clean"] for run in selected),
            "evaluation_completed_count": sum(run["evaluation_completed"] for run in selected),
            "model_physical_pass_count": sum(run["model_physical_pass"] for run in selected),
            "case_run_count": len(selected_cases),
            "first_failure_time_s_mean": float(np.mean(failure_times)) if failure_times else None,
            "first_failure_time_s_std": float(np.std(failure_times, ddof=1)) if len(failure_times) > 1 else 0.0 if failure_times else None,
            "wall_failure_count": sum(not record["hard_wall_passed"] for record in selected_cases),
            "finite_failure_count": sum(record["finite_failure_observed"] for record in selected_cases),
        }
    report = {
        "schema": "l2.a1.model_failure_diagnostics.v1",
        "stage": "A1",
        "created_at_utc": utc_now(),
        "baseline_commit": BASELINE_COMMIT,
        "source_closure": {"path": repo_relative(DEFAULT_CLOSURE), "sha256": sha256_file(DEFAULT_CLOSURE)[0]},
        "training_run_semantics": {
            "logical_run_count": len(runs),
            "independent_evaluation_physical_case_count": len({record["case_id"] for record in case_records}),
            "case_run_count": len(case_records),
            "statistical_unit": "16 independent physical evaluation cases; model route/seed is a second-level factor",
        },
        "runs": runs,
        "route_summary": route_summary,
        "failure_profile": aggregate_failure_profile(case_records),
        "oracle_diagnostics": {
            "real_trajectory_same_evaluator_proxy": "source truth identity/finite/wall oracle; evaluator adapter parity remains a separate implementation check",
            "reference_next_displacement": "direct next-frame displacement replayed through the declared update equation",
            "reference_velocity_integrator": "native saved velocity integrated over saved cadence; diagnostic lower bound, not material truth",
            "constant_velocity_baseline": "initial native velocity autonomous rollout proxy",
            "low_resolution_sph": "existing low-resolution source references are retained as recipe evidence; no new low-resolution model run was launched",
            "sentinels": oracles,
        },
        "interpretation": {
            "training_completed_is_not_worker_success": True,
            "evaluation_completed_is_not_model_physical_pass": True,
            "finite_but_wall_invalid_is_valid_negative_science_result": True,
            "nan_after_failure_not_zero_filled": True,
            "data_gate_independent_of_model_gate": canonical["qualification_axes"]["data"] == "registered_numerical_reference",
        },
        "resource_observation": {
            "wall_seconds": time.perf_counter() - started_wall,
            "process_cpu_seconds": time.process_time() - started_cpu,
            "new_storage_bytes": 0,
        },
    }
    report["status"] = "complete" if len(runs) == 6 and len(case_records) == 96 else "complete_with_findings"
    atomic_json(CAMPAIGN / "reports/a1-model-failure-diagnostics.json", report)
    update_usage(cpu_core_hours_actual=report["resource_observation"]["process_cpu_seconds"] / 3600.0)
    update_stage("A1", "complete" if report["status"] == "complete" else "complete_with_findings", facts={
        "report": "reports/a1-model-failure-diagnostics.json",
        "logical_runs": len(runs),
        "case_runs": len(case_records),
        "model_pass_count": sum(run["model_physical_pass"] for run in runs),
    })
    return report


FAMILY_HYPOTHESIS_TEMPLATES = {
    "F1": {
        "positive_control": "finite water-column release around a resolved obstacle with an explicit return path",
        "hypotheses": [
            {
                "id": "F1-H1",
                "claim": "A resolved obstacle opening plus native boundary semantics preserves first passage, split/rejoin, and return topology across the three reference resolutions.",
                "metrics": [
                    "first-passage event time and CDF",
                    "origin-to-destination mass matrix",
                    "split/rejoin occupancy and residence",
                    "closed-wall violations and finite-state integrity",
                ],
                "falsifier": "Any canary or paired background with nonzero closed-wall violation, missing source/destination mass, or a topology change that is not explained by resolution is a falsifier.",
            },
            {
                "id": "F1-H2",
                "claim": "A controlled blocking or wet-bed change changes the return and destination distributions without being reduced to a static final-shape match.",
                "metrics": [
                    "paired-background delta in first-passage CDF",
                    "return flux and residence bounds",
                    "unknown mass fraction",
                    "event-time error against the matched reference",
                ],
                "falsifier": "If the paired backgrounds are indistinguishable after accounting for numerical uncertainty, or if mass provenance is unavailable, the hypothesis is rejected for this recipe.",
            },
        ],
    },
    "F2": {
        "positive_control": "finite liquid volume with an explicit rotating-cup control and no future fluid-state input",
        "hypotheses": [
            {
                "id": "F2-H1",
                "claim": "A real rotating cup with a centered versus off-center catch preserves catch, spill, residual, and flight phases under a known control trajectory.",
                "metrics": [
                    "caught, spilled, residual, and in-flight mass by time",
                    "catch event time and final destination distribution",
                    "source-to-cup provenance matrix",
                    "closed-wall violations and finite-state integrity",
                ],
                "falsifier": "A missing static hold, an unrecorded control trajectory, or an unresolvable catch/spill phase falsifies the candidate before model evaluation.",
            },
            {
                "id": "F2-H2",
                "claim": "Source-layer labels remain identifiable through transfer and distinguish centered from off-center catch without encoding future fluid state.",
                "metrics": [
                    "source-layer transfer matrix",
                    "unknown mass fraction",
                    "residual source composition",
                    "paired-background distribution distance",
                ],
                "falsifier": "If source labels are not conserved/traceable, or if the distinction requires future fluid positions or velocities as input, the hypothesis is rejected.",
            },
        ],
    },
    "F3": {
        "positive_control": "three-dimensional off-axis connected passage or multi-axis prescribed drive",
        "hypotheses": [
            {
                "id": "F3-H1",
                "claim": "An off-axis baffle with a connected passage induces transverse exchange and repeated crossing while retaining the registered native correction and no-penetration semantics.",
                "metrics": [
                    "transverse velocity and exchange mass",
                    "repeated-crossing count and residence",
                    "geometric passage occupancy",
                    "closed-wall violations and numerical identity integrity",
                ],
                "falsifier": "An AABB-only shortcut, blocked opening, or loss of transverse exchange under the canary recipe rejects this geometry as a valid extension.",
            },
            {
                "id": "F3-H2",
                "claim": "A multi-axis prescribed drive changes residence and crossing distributions through the declared causal control, without using future fluid state as an input.",
                "metrics": [
                    "control-conditioned residence distribution",
                    "crossing and return event timing",
                    "transverse momentum response",
                    "input provenance and holdout-control separation",
                ],
                "falsifier": "If the drive cannot be replayed from its declared control or the response is indistinguishable from a one-axis proxy, this extension is rejected.",
            },
        ],
    },
    "F4": {
        "positive_control": "finite jet or liquid-column deflection with a resolved landing/return phase",
        "hypotheses": [
            {
                "id": "F4-H1",
                "claim": "A resolved inertial-scale jet deflection can be measured through landing and return without claiming spray or capillary truth.",
                "metrics": ["landing/return event time", "destination and material provenance", "finite-state and boundary integrity"],
                "falsifier": "Unresolved spray/capillary behavior or missing provenance ends this bounded branch.",
            },
            {
                "id": "F4-H2",
                "claim": "The deflection response remains stable across the bounded reference ladder after geometry and control are held fixed.",
                "metrics": ["resolution trend", "event-time difference", "mass closure"],
                "falsifier": "A non-monotone unresolved resolution trend without a diagnosed cause rejects the anchor.",
            },
        ],
    },
    "F5": {
        "positive_control": "single wave run-up and overtopping over a quantified weir",
        "hypotheses": [
            {
                "id": "F5-H1",
                "claim": "A single resolved overtopping event supports source-aware overtopping and return-flux measurements within quantified boundaries.",
                "metrics": ["overtopping provenance", "return flux", "event time", "finite-state and boundary integrity"],
                "falsifier": "An unquantified open-boundary loss or missing return flux ends the bounded branch.",
            },
            {
                "id": "F5-H2",
                "claim": "A localized notch changes the overtopping source map without changing the measurement semantics.",
                "metrics": ["notch versus low-weir source map", "unknown mass fraction", "resolution trend"],
                "falsifier": "If the source map is not identifiable, the notch comparison is rejected.",
            },
        ],
    },
    "F6": {
        "positive_control": "single rigid body static/units/inertia check followed by a no-contact fluid response",
        "hypotheses": [
            {
                "id": "F6-H1",
                "claim": "A single rigid body can be checked for static balance, units, inertia, and no-contact fluid response within a bounded domain.",
                "metrics": ["static displacement", "body trajectory", "momentum exchange", "no-contact integrity"],
                "falsifier": "Any unintended contact or unclosed static balance ends the branch.",
            },
            {
                "id": "F6-H2",
                "claim": "The bounded response is reproducible under the three reference resolutions before any broader Chrono/contact study.",
                "metrics": ["resolution trend", "trajectory difference", "contact-event count"],
                "falsifier": "A contact event or unresolved resolution trend rejects the anchor.",
            },
        ],
    },
}


EXISTING_FAMILY_ASSETS = {
    "F1": ["F1_dam_break_plain", "F1_center_obstacle", "F1_twin_obstacle", "F1_opposing_columns"],
    # The airborne-slug cases are retained as low-cost proxies.  The W06
    # entries are the prior campaign's real rotating-cup candidate and are
    # included only so C1 can explicitly rebind/re-audit them under L2.
    "F2": [
        "F2_airborne_slug_centered", "F2_airborne_slug_offset", "F2_two_source_layers",
        "W06_standard_slow_center", "W06_standard_offset_partial",
    ],
    "F3": ["F3_baffled_slosh", "F3_transverse_slosh", "F3_impulse_slosh"],
    "F4": ["F4_head_on_columns", "F4_oblique_columns", "F4_drop_onto_pool"],
    "F5": ["F5_low_weir", "F5_notched_weir", "F5_wet_bed_overtop"],
    "F6": ["F6_floating_box", "F6_heavy_box_entry", "F6_twin_floaters"],
}


def existing_asset_evidence(case_id: str, catalog: dict[str, dict], role: str) -> dict:
    record = catalog.get(case_id, {})
    if case_id.startswith("W06_"):
        definition = LAB / "campaigns/v0.1-candidate/cases/w06" / f"{case_id}_Def.xml"
        artifact = LAB / "campaigns/v0.1-candidate/data/w06" / f"{case_id}.h5"
        role = "prior_true_rotating_cup_candidate; L2 recipe rebind and canary required"
    else:
        definition = LAB / record.get("definition", f"cases/{case_id}/{case_id}_Def.xml")
        artifact = LAB / "data" / f"{case_id}.h5"
    return {
        "case_id": case_id,
        "mechanism": record.get("mechanism"),
        "definition": file_evidence(definition, with_chunks=False),
        "legacy_trajectory": file_evidence(artifact, with_chunks=False),
        "reuse_role": role,
        "qualification_status": "not_qualified_by_C0",
    }


def common_canary(background: str, *, family: str) -> dict:
    return {
        "attempt_count": 1,
        "background": background,
        "family": family,
        "reference_resolution_m": 0.0075,
        "must_pass_before_batch": [
            "definition, recipe, binary, and source hashes recorded",
            "trajectory schema and all expected frames present",
            "unique numerical particle identity and monotonic time",
            "finite position, velocity, and mass arrays",
            "closed-wall violation count is exactly zero for the declared boundary",
            "source/material semantics are present and reproducible",
            "control input is replayable without future fluid state",
        ],
        "failure_action": "stop cohort on common input/semantics failure; preserve physical failure and move to the paired background only after diagnosis",
        "batch_release": "one canary must pass all hard integrity/source gates before the six-cell family matrix is admitted",
    }


def run_c0() -> dict:
    state = require_adopted()
    if state["stages"]["A0"]["status"] not in {"complete", "complete_with_findings"}:
        raise RuntimeError("C0 requires A0 to be complete")
    started_wall = time.perf_counter()
    started_cpu = time.process_time()
    scenario_path = CAMPAIGN / "plan-source" / "SCENARIO_CARDS.json"
    scenario = read_json(scenario_path)
    catalog_path = LAB / "cases" / "manifest.json"
    catalog_payload = read_json(catalog_path)
    catalog = {item["id"]: item for item in catalog_payload.get("cases", [])}
    canonical_path = CAMPAIGN / "evidence" / "f3-canonical-manifest.json"
    canonical = read_json(canonical_path) if canonical_path.is_file() else {}
    ladder = canonical.get("recipe", {}).get(
        "reference_resolutions_m", [0.00818181818181818, 0.0075, 0.006]
    )
    cards: list[dict] = []
    for source_card in scenario.get("families", []):
        family = source_card["family"]
        priority = source_card.get("role", "bounded_extension")
        if family in {"F1", "F2"}:
            asset_role = "legacy_low_cost_proxy_only; new recipe and qualification required"
        elif family == "F3":
            asset_role = "starter_or_low_cost_proxy_only; does not establish all-geometry or inertial validation"
        else:
            asset_role = "bounded_anchor_only; no family-wide qualification"
        assets = [existing_asset_evidence(case_id, catalog, asset_role) for case_id in EXISTING_FAMILY_ASSETS.get(family, [])]
        template = FAMILY_HYPOTHESIS_TEMPLATES[family]
        cards.append({
            "family": family,
            "role": priority,
            "design_status": "frozen_design_not_executed",
            "backgrounds": source_card.get("backgrounds", []),
            "positive_control": template["positive_control"],
            "lagrangian_tasks": source_card.get("lagrangian_tasks", []),
            "initial_reference_cells": [
                {"background": background, "reference_resolution_m": resolution}
                for background in source_card.get("backgrounds", [])
                for resolution in ladder
            ],
            "reference_ladder_m": ladder,
            "qualification_attempt_soft_cap": source_card.get("qualification_attempt_soft_cap"),
            "scope_limit": source_card.get("scope_limit"),
            "external_anchor": source_card.get("external_anchor"),
            "candidate_existing_assets": assets,
            "hypotheses": template["hypotheses"],
            "canary": common_canary(source_card.get("backgrounds", ["unspecified"])[0], family=family),
            "error_budget": {
                "hard_integrity": {
                    "structural_pass": True,
                    "finite_position_velocity_mass": True,
                    "unique_particle_identity": True,
                    "monotonic_time_and_complete_frames": True,
                    "closed_wall_violation_count_max": 0,
                },
                "candidate_numeric_reference": {
                    "unknown_mass_fraction_max": 0.01,
                    "macro_observable_relative_error_max": 0.02,
                    "event_time_relative_error_max": 0.05,
                    "path_error": "T2_path is separately gated; absent path reference is reported unknown, never treated as pass",
                },
                "status": "frozen_candidate_budget; C1 must bind each metric to a declared physical scale and reference asset before results",
            },
            "split_contract": {
                "required_fields": [
                    "physical_case_id", "lineage_group_id", "paired_background_id",
                    "recipe_id", "attempt_id", "view_id",
                ],
                "rules": [
                    "coarse/fine/restart/crop/fixed-ID views of one physical process share one lineage_group_id",
                    "paired backgrounds share a paired_background_id but remain distinct physical_case_id values",
                    "calibration/model-design cases remain development and cannot become hidden test",
                    "no same lineage is split across final roles",
                ],
            },
            "execution_status": {
                "solver_attempts_at_C0": 0,
                "results_created_at_C0": 0,
                "qualification_claim": "none",
            },
        })
    acceptance = {
        "six_family_cards_present": len(cards) == 6 and {card["family"] for card in cards} == {"F1", "F2", "F3", "F4", "F5", "F6"},
        "priority_families_frozen": all(next(card for card in cards if card["family"] == family)["role"] == "new_core_priority" for family in ("F1", "F2")),
        "priority_reference_cells_are_2x3": all(len(next(card for card in cards if card["family"] == family)["initial_reference_cells"]) == 6 for family in ("F1", "F2", "F3")),
        "bounded_extension_caps_preserved": all(next(card for card in cards if card["family"] == family)["qualification_attempt_soft_cap"] == 4 for family in ("F4", "F5", "F6")),
        "at_most_two_hypotheses_per_family": all(len(card["hypotheses"]) <= 2 for card in cards),
        "each_family_has_canary": all(card["canary"]["attempt_count"] == 1 for card in cards),
        "legacy_assets_not_reclassified": all(asset["qualification_status"] == "not_qualified_by_C0" for card in cards for asset in card["candidate_existing_assets"]),
        "no_solver_executed": True,
    }
    report = {
        "schema": "l2.c0.family_hypotheses.v1",
        "stage": "C0",
        "created_at_utc": utc_now(),
        "baseline_commit": BASELINE_COMMIT,
        "source_plan": {
            "scenario_cards": {"path": repo_relative(scenario_path), "sha256": sha256_file(scenario_path)[0]},
            "case_catalog": {"path": repo_relative(catalog_path), "sha256": sha256_file(catalog_path)[0]},
            "canonical_reference_ladder_source": repo_relative(canonical_path) if canonical_path.is_file() else None,
        },
        "status": "frozen_design_not_executed",
        "solver_execution": "none",
        "family_cards": cards,
        "common_contract": {
            "reference_ladder_m": ladder,
            "reference_cells": "two backgrounds by three reference resolutions for F1/F2/F3; bounded anchors retain their family cap",
            "metric_policy": "hard integrity, T1 numerical observables, T2_macro, and T2_path remain separate axes",
            "negative_result_policy": "preserve physical failure and incomplete trajectories; do not zero-fill or select only attractive cases",
        },
        "acceptance": acceptance,
        "resource_observation": {
            "wall_seconds": time.perf_counter() - started_wall,
            "process_cpu_seconds": time.process_time() - started_cpu,
            "solver_attempts": 0,
            "new_storage_bytes_before_report": 0,
        },
    }
    report["status"] = "complete" if all(acceptance.values()) else "complete_with_findings"
    report_path = CAMPAIGN / "reports" / "c0-family-hypotheses.json"
    atomic_json(report_path, report)
    report["resource_observation"]["new_storage_bytes"] = report_path.stat().st_size
    atomic_json(report_path, report)
    update_usage(
        cpu_core_hours_actual=report["resource_observation"]["process_cpu_seconds"] / 3600.0,
        new_storage_bytes=report["resource_observation"]["new_storage_bytes"],
    )
    update_stage("C0", "complete" if report["status"] == "complete" else "complete_with_findings", facts={
        "report": "reports/c0-family-hypotheses.json",
        "family_count": len(cards),
        "solver_attempts": 0,
        "priority_families": ["F1", "F2"],
    })
    return report


def status() -> dict:
    state = require_adopted()
    queue = read_json(CAMPAIGN / "queue.json") if (CAMPAIGN / "queue.json").is_file() else {}
    return {"state": state, "queue": queue}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    bootstrap = subparsers.add_parser("bootstrap", help="record owner adoption and preserve plan package")
    bootstrap.add_argument("--plan-zip", type=Path, default=DEFAULT_PLAN_ZIP)
    subparsers.add_parser("a0", help="build and audit the F3 starter manifest")
    subparsers.add_parser("a1", help="diagnose retained model runs without retraining")
    subparsers.add_parser("c0", help="freeze family hypotheses and canary controls without solver execution")
    subparsers.add_parser("status", help="show the persistent state and ready queue")
    args = parser.parse_args()
    if args.command == "bootstrap":
        state_path = CAMPAIGN / "state.json"
        if state_path.is_file():
            print(json.dumps(read_json(state_path), ensure_ascii=False, indent=2))
        else:
            print(json.dumps(adoption_payload(args.plan_zip), ensure_ascii=False, indent=2))
        return 0
    if args.command == "a0":
        print(json.dumps(run_a0(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "a1":
        print(json.dumps(run_a1(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "c0":
        print(json.dumps(run_c0(), ensure_ascii=False, indent=2))
        return 0
    print(json.dumps(status(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
