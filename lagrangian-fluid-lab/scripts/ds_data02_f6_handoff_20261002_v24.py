#!/usr/bin/env python3
"""F6 coarse/fine native post-processing and pose diagnostics.

This is an additive continuation of the frozen v19--v23 handoff scripts.  It
does not rerun a solver, alter any consumed H5/label, or treat the reused
DOMAIN_X_REPAIR_01 medium run as a new independent resolution.  The four
DOMAIN_XY_REPAIR_02 coarse/fine native trees are audited through the shared v2
CPU runner, converted with the v20 XML rigid contract, and receive a separate
native-particle Kabsch pose diagnostic.  The diagnostic is stored alongside
the source FloatingInfo pose; it does not silently replace the source state.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

try:
    import numpy as np
except (ImportError, OSError, ValueError):
    np = None  # type: ignore[assignment]
try:
    import h5py
except (ImportError, OSError, ValueError):  # system Python may have an ABI mismatch
    h5py = None  # type: ignore[assignment]


SCRIPT = Path(__file__).resolve()


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V16 = _load("f6_handoff_v16_for_v24", SCRIPT.with_name("ds_data02_f6_handoff_20261002_v16.py"))
V19 = _load("f6_handoff_v19_for_v24", SCRIPT.with_name("ds_data02_f6_handoff_20261002_v19.py"))
V20 = _load("f6_handoff_v20_for_v24", SCRIPT.with_name("ds_data02_f6_handoff_20261002_v20.py"))

FAMILY_ROOT = V16.FAMILY_ROOT
RAW_ROOT = V16.RAW_ROOT
INTEGRATION_LAB = V16.INTEGRATION_LAB
VENV_PYTHON = V19.VENV_PYTHON  # preserve the literal venv path; do not resolve it
RUNTIME_V2 = V16.RUNTIME_V2
FLOATING_INFO = V16.FLOATING_INFO
COMPUTE_FORCES = V16.COMPUTE_FORCES
LABEL_CONFIGS = {
    "simple_free_response": V16.SIMPLE_LABEL_CONFIG,
    "wave_no_contact": V16.WAVE_LABEL_CONFIG,
}
POST_ROOT = FAMILY_ROOT / "postprocessing_007"
REQUEST_ROOT = POST_ROOT / "execution_requests"
MANIFEST_ROOT = POST_ROOT / "raw_tree_manifests"
MECHANISMS = ("simple_free_response", "wave_no_contact")
RESOLUTIONS = ("coarse", "fine")
ALL_RESOLUTIONS = ("coarse", "medium", "fine")
CENTER = np.asarray([2.4, 1.2, 1.08], dtype=np.float64) if np is not None else None


def sha256(path: Path) -> str:
    return V16.sha256(Path(path))


def read_json(path: Path) -> dict[str, Any]:
    return V16.read_json(Path(path))


def write_json(path: Path, value: Any) -> None:
    V16.write_json(Path(path), value)


def _case(mechanism: str, resolution: str) -> dict[str, Any]:
    manifest = V16._manifest()
    for row in manifest["cases"]:
        if row["mechanism_id"] == mechanism and row["resolution_id"] == resolution:
            return row
    raise KeyError((mechanism, resolution))


def _paths(mechanism: str, resolution: str) -> dict[str, Path]:
    case = _case(mechanism, resolution)
    cid = str(case["case_id"])
    gencase = V16._generated_paths(case)
    solver_root = RAW_ROOT / cid / f"{cid}_SOLVER_QUAL_001"
    output = solver_root / "solver_output"
    data = output / "data"
    return {
        "case": Path(cid),
        "gencase_root": gencase["root"],
        "gencase_receipt": gencase["receipt"],
        "xml": gencase["xml"],
        "gencase_prefix": gencase["prefix"],
        "solver_root": solver_root,
        "solver_receipt": solver_root / "execution-receipt.json",
        "output": output,
        "data": data,
        "runout": output / "Run.out",
        "runparts": output / "RunPARTs.csv",
    }


def _cid(mechanism: str, resolution: str) -> str:
    return str(_case(mechanism, resolution)["case_id"])


def _unique_files(values: list[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for value in values:
        path = Path(value)
        key = str(path) if path == VENV_PYTHON else str(path.resolve())
        if key not in seen:
            seen.add(key)
            result.append(path)
    missing = [str(path) for path in result if not path.is_file()]
    if missing:
        raise FileNotFoundError("F6 v24 input missing: " + ", ".join(missing))
    return result


def _strings(values: list[Path]) -> list[str]:
    return [str(path) if path == VENV_PYTHON else str(path.resolve()) for path in values]


def _source_manifest(mechanism: str, resolution: str) -> Path:
    paths = _paths(mechanism, resolution)
    data = paths["data"]
    if not data.is_dir():
        raise FileNotFoundError(data)
    frames = sorted(data.glob("Part_[0-9]*.bi4"), key=lambda p: int(re.search(r"(\d+)", p.stem).group(1)))
    if [int(re.search(r"(\d+)", p.stem).group(1)) for p in frames] != list(range(241)):
        raise ValueError(f"F6 v24 requires native Part_0000..Part_0240: {data}")
    manifest = V16._tree_manifest(data)
    manifest_path = MANIFEST_ROOT / f"{mechanism}_{resolution}_domain_xy_repair_02.json"
    write_json(manifest_path, manifest)
    return manifest_path


def _source_inputs(mechanism: str, resolution: str, manifest_path: Path) -> list[Path]:
    paths = _paths(mechanism, resolution)
    cid = _cid(mechanism, resolution)
    all_dp = FAMILY_ROOT / "all_dp_preflight_001.json"
    repair_manifest = FAMILY_ROOT / "manifest.json"
    values = [
        SCRIPT,
        SCRIPT.with_name("ds_data02_f6_handoff_20261002_v16.py"),
        SCRIPT.with_name("ds_data02_f6_handoff_20261002_v19.py"),
        SCRIPT.with_name("ds_data02_f6_handoff_20261002_v20.py"),
        V16.V15,
        V16.V14,
        V16.V13,
        V16.V12,
        RUNTIME_V2,
        V16.CONVERTER,
        V16.NATIVE_LABELS,
        V16.OFFICIAL_TEMPLATE,
        FLOATING_INFO,
        COMPUTE_FORCES,
        repair_manifest,
        all_dp,
        manifest_path,
        paths["gencase_receipt"],
        paths["xml"],
        paths["solver_receipt"],
        paths["runout"],
        paths["runparts"],
        paths["data"] / "Part_Head.ibi4",
        paths["data"] / "PartFloatInfo.ibi4",
        paths["data"] / "PartMotionRef.ibi4",
        paths["data"] / "PartOut_000.obi4",
        paths["data"] / "Part_0000.bi4",
        paths["data"] / "Part_0240.bi4",
        paths["gencase_prefix"].with_suffix(".bi4"),
        paths["gencase_prefix"].with_name(paths["gencase_prefix"].name + "_All.vtk"),
        paths["gencase_prefix"].with_name(paths["gencase_prefix"].name + "_Bound.vtk"),
        paths["gencase_prefix"].with_name(paths["gencase_prefix"].name + "_Fluid.vtk"),
    ]
    return _unique_files(values)


def _common(mechanism: str, resolution: str, inputs: list[Path], manifest_path: Path) -> dict[str, Any]:
    paths = _paths(mechanism, resolution)
    cid = _cid(mechanism, resolution)
    strings = _strings(inputs)
    return {
        "schema": "ds02.runner.request.v1",
        "family_id": "F6",
        "case_id": cid,
        "mechanism_id": mechanism,
        "resolution_id": resolution,
        "source_solver_attempt": str(paths["solver_receipt"].resolve()),
        "source_solver_receipt_sha256": sha256(paths["solver_receipt"]),
        "source_raw_tree_manifest": str(manifest_path.resolve()),
        "source_raw_tree_manifest_sha256": sha256(manifest_path),
        "input_files": strings,
        "input_hashes_at_request": {key: sha256(Path(key)) for key in strings},
        "worktree_root": str(V16.MODULE.REPO_ROOT.resolve()),
        "cwd": str(INTEGRATION_LAB.resolve()),
        "source_hash_binding": "v24 verifies the complete immutable Part_*.bi4 tree before and after every task; selected solver/XML/control provenance is runner-hashed",
        "gpu_launch": False,
        "q_n_status": "pending_native_postprocessing_and_scientific_review",
    }


def prepare_audits() -> dict[str, Any]:
    """Register four FloatingInfo and four ComputeForces CPU audits."""

    REQUEST_ROOT.mkdir(parents=True, exist_ok=True)
    MANIFEST_ROOT.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for mechanism in MECHANISMS:
        for resolution in RESOLUTIONS:
            paths = _paths(mechanism, resolution)
            manifest_path = _source_manifest(mechanism, resolution)
            inputs = _source_inputs(mechanism, resolution, manifest_path)
            common = _common(mechanism, resolution, inputs, manifest_path)
            cid = _cid(mechanism, resolution)
            floating_attempt = f"{cid}_FLOATINGINFO_CF_001"
            floating = {
                **common,
                "attempt_id": floating_attempt,
                "kind": "cpu",
                "cpu_task_kind": "audit",
                "cpu_threads": 2,
                "max_wall_seconds": 600,
                "estimated_storage_bytes": 268435456,
                "command": [str(VENV_PYTHON), str(SCRIPT), "run-floating-info", "--data-dir", str(paths["data"].resolve()), "--manifest", str(manifest_path.resolve()), "--output-prefix", "{attempt_root}/floatinginfo/FloatingMotion"],
                "purpose": "official full native FloatingInfo pose/orientation/quaternion/linear-angular velocity audit for a completed DOMAIN_XY_REPAIR_02 coarse/fine solver tree",
                "required_state_fields": ["pose", "orientation", "quaternion", "linear_velocity", "angular_velocity", "fluid_force", "fluid_torque"],
                "output_contract": {"csv": "FloatingMotion_mk60.csv", "frames": 241, "window_s": [0.0, 12.0]},
            }
            floating_path = REQUEST_ROOT / f"{cid}_floatinginfo_cf_001.json"
            write_json(floating_path, floating)
            rows.append({"path": str(floating_path.resolve()), "sha256": sha256(floating_path), "kind": "floatinginfo", "case_id": cid, "resolution_id": resolution})

            force_attempt = f"{cid}_COMPUTEFORCES_CF_001"
            force = {
                **common,
                "attempt_id": force_attempt,
                "kind": "cpu",
                "cpu_task_kind": "audit",
                "cpu_threads": 2,
                "max_wall_seconds": 600,
                "estimated_storage_bytes": 268435456,
                "command": [str(VENV_PYTHON), str(SCRIPT), "run-compute-forces", "--data-dir", str(paths["data"].resolve()), "--manifest", str(manifest_path.resolve()), "--generated-xml", str(paths["xml"].resolve()), "--output-prefix", "{attempt_root}/forces/FloatingForce"],
                "purpose": "official ComputeForces fluid force and fixed-reference moment audit; raw moment origin is retained explicitly and is not relabeled as current COM",
                "required_state_fields": ["force", "torque", "massbody", "inertia"],
                "moment_reference": {"compute_forces_input_point_m": [2.4, 1.2, 1.08], "semantic": "fixed initial XML body center supplied to ComputeForces; not native FloatingInfo current-COM force angle"},
                "output_contract": {"csv": "FloatingForce.csv", "frames": 241, "window_s": [0.0, 12.0]},
            }
            force_path = REQUEST_ROOT / f"{cid}_computeforces_cf_001.json"
            write_json(force_path, force)
            rows.append({"path": str(force_path.resolve()), "sha256": sha256(force_path), "kind": "computeforces", "case_id": cid, "resolution_id": resolution})
    result = {
        "schema": "ds-data-02.f6.rigid003.postprocessing_007.audit_requests_001.v1",
        "family_id": "F6",
        "status": "prepared_cpu_audit_requests",
        "requests": rows,
        "source_scope": "four independent DOMAIN_XY_REPAIR_02 coarse/fine raw solver trees",
        "medium_reuse": {"independent_solver_case": False, "source": "DOMAIN_X_REPAIR_01 medium actual native input; not recreated here"},
        "gpu_launch": False,
        "conversion_launch": False,
        "qualification_claim": "none",
        "q_n_status": "pending actual CPU audits and native conversion",
    }
    write_json(POST_ROOT / "audit_request_manifest_001.json", result)
    return result


def _receipt_for(attempt_id: str, case_id: str) -> Path:
    return RAW_ROOT / case_id / attempt_id / "execution-receipt.json"


def _require_completed(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    receipt = read_json(path)
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise RuntimeError(f"CPU source task is not completed: {path}: {receipt.get('status')} {receipt.get('returncode')}")
    return receipt


def _motion_csv(case_id: str) -> Path:
    path = RAW_ROOT / case_id / f"{case_id}_FLOATINGINFO_CF_001" / "floatinginfo" / "FloatingMotion_mk60.csv"
    if not path.is_file():
        raise FileNotFoundError(f"completed v24 FloatingInfo CSV missing: {path}")
    return path


def prepare_conversions() -> dict[str, Any]:
    """Register four enriched sparse H5 conversions after audits complete."""

    REQUEST_ROOT.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for mechanism in MECHANISMS:
        for resolution in RESOLUTIONS:
            cid = _cid(mechanism, resolution)
            _require_completed(_receipt_for(f"{cid}_FLOATINGINFO_CF_001", cid))
            _require_completed(_receipt_for(f"{cid}_COMPUTEFORCES_CF_001", cid))
            paths = _paths(mechanism, resolution)
            manifest_path = MANIFEST_ROOT / f"{mechanism}_{resolution}_domain_xy_repair_02.json"
            motion = _motion_csv(cid)
            inputs = _source_inputs(mechanism, resolution, manifest_path)
            inputs.extend([motion, _receipt_for(f"{cid}_FLOATINGINFO_CF_001", cid), _receipt_for(f"{cid}_COMPUTEFORCES_CF_001", cid)])
            inputs = _unique_files(inputs)
            common = _common(mechanism, resolution, inputs, manifest_path)
            attempt = f"{cid}_NATIVE_H5_CF_001"
            output = RAW_ROOT / cid / attempt / "trajectory.h5"
            report = RAW_ROOT / cid / attempt / "conversion-report.json"
            request = {
                **common,
                "attempt_id": attempt,
                "kind": "cpu",
                "cpu_task_kind": "conversion",
                "cpu_threads": 4,
                "max_wall_seconds": 2400,
                "estimated_storage_bytes": 4294967296,
                "command": [str(VENV_PYTHON), str(SCRIPT), "run-enriched-conversion", "--case-id", cid, "--data-dir", str(paths["data"].resolve()), "--generated-xml", str(paths["xml"].resolve()), "--motion-csv", str(motion.resolve()), "--manifest", str(manifest_path.resolve()), "--output", "{attempt_root}/trajectory.h5", "--report", "{attempt_root}/conversion-report.json"],
                "purpose": "full native BI4-to-HDF5 conversion with v20 positive XML mass/inertia metadata and additive all-frame native floating-particle Kabsch diagnostic",
                "required_rigid_state_fields": ["pose", "orientation", "quaternion", "linear_velocity", "angular_velocity", "force", "torque", "massbody", "inertia"],
                "required_native_fit_fields": ["native_fit_position", "native_fit_quaternion_xyzw", "native_fit_rotation_matrix", "native_fit_residual_rms_m", "native_fit_residual_max_m"],
                "source_motion_csv": str(motion.resolve()),
                "source_motion_csv_sha256": sha256(motion),
                "output_contract": {"trajectory": str(output), "report": str(report), "frames": 241, "window_s": [0.0, 12.0], "source_h5_004_immutable": True},
                "conversion_concurrency_note": "run one v24 conversion at a time; leave one global conversion slot for F3",
            }
            path = REQUEST_ROOT / f"{cid}_native_h5_cf_001.json"
            write_json(path, request)
            rows.append({"path": str(path.resolve()), "sha256": sha256(path), "kind": "conversion", "case_id": cid, "resolution_id": resolution})
    result = {
        "schema": "ds-data-02.f6.rigid003.postprocessing_007.conversion_requests_001.v1",
        "family_id": "F6",
        "status": "prepared_after_terminal_cpu_audits",
        "requests": rows,
        "gpu_launch": False,
        "conversion_launch": False,
        "medium_reuse": {"independent_solver_case": False, "medium_source_case": "F6_HANDOFF_20261002_*_DOMAIN_X_REPAIR_01_MEDIUM"},
        "qualification_claim": "none",
        "q_n_status": "pending four actual H5 conversions and labels",
    }
    write_json(POST_ROOT / "conversion_request_manifest_001.json", result)
    return result


def prepare_labels() -> dict[str, Any]:
    """Register labels only after the four new H5 files are terminal."""

    REQUEST_ROOT.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for mechanism in MECHANISMS:
        for resolution in RESOLUTIONS:
            cid = _cid(mechanism, resolution)
            conversion_attempt = f"{cid}_NATIVE_H5_CF_001"
            conversion_receipt = _require_completed(_receipt_for(conversion_attempt, cid))
            source = RAW_ROOT / cid / conversion_attempt / "trajectory.h5"
            report = source.with_name("conversion-report.json")
            if not source.is_file() or not report.is_file():
                raise FileNotFoundError(source)
            paths = _paths(mechanism, resolution)
            manifest_path = MANIFEST_ROOT / f"{mechanism}_{resolution}_domain_xy_repair_02.json"
            inputs = _source_inputs(mechanism, resolution, manifest_path)
            inputs.extend([source, report, conversion_receipt and _receipt_for(conversion_attempt, cid), LABEL_CONFIGS[mechanism], V16.NATIVE_LABELS])
            inputs = _unique_files(inputs)
            common = _common(mechanism, resolution, inputs, manifest_path)
            attempt = f"{cid}_LABELS_CF_001"
            output = RAW_ROOT / cid / attempt / "native-labels.h5"
            config = LABEL_CONFIGS[mechanism]
            request = {
                **common,
                "attempt_id": attempt,
                "kind": "cpu",
                "cpu_task_kind": "labels",
                "cpu_threads": 2,
                "max_wall_seconds": 1200,
                "estimated_storage_bytes": 1073741824,
                "command": [str(VENV_PYTHON), str(SCRIPT), "run-labels", "--source", str(source.resolve()), "--config", str(config.resolve()), "--output", "{attempt_root}/native-labels.h5"],
                "purpose": "materialize native type-3 source/destination and first-passage labels for a completed v24 trajectory; no model invocation",
                "source_trajectory": str(source.resolve()),
                "source_trajectory_sha256": sha256(source),
                "source_conversion_receipt": str(_receipt_for(conversion_attempt, cid).resolve()),
                "source_conversion_receipt_sha256": sha256(_receipt_for(conversion_attempt, cid)),
                "required_label_semantics": ["fluid_type3_only", "fixed_native_identity", "finite_saved_frame_chord_events", "mass_ledger", "no_model"],
                "output_contract": {"output": str(output), "frames": 241, "window_s": [0.0, 12.0]},
            }
            path = REQUEST_ROOT / f"{cid}_labels_cf_001.json"
            write_json(path, request)
            rows.append({"path": str(path.resolve()), "sha256": sha256(path), "kind": "labels", "case_id": cid, "resolution_id": resolution})
    result = {
        "schema": "ds-data-02.f6.rigid003.postprocessing_007.label_requests_001.v1",
        "family_id": "F6",
        "status": "prepared_after_terminal_h5_conversions",
        "requests": rows,
        "gpu_launch": False,
        "qualification_claim": "none",
        "q_n_status": "pending four actual labels and all-resolution comparison",
    }
    write_json(POST_ROOT / "label_request_manifest_001.json", result)
    return result


def _quat_from_rotation(r: "np.ndarray") -> "np.ndarray":
    """Convert a proper column-vector rotation matrix to xyzw."""

    q = np.empty(4, dtype=np.float64)
    trace = float(np.trace(r))
    if trace > 0.0:
        s = math.sqrt(trace + 1.0) * 2.0
        q[3] = 0.25 * s
        q[0] = (r[2, 1] - r[1, 2]) / s
        q[1] = (r[0, 2] - r[2, 0]) / s
        q[2] = (r[1, 0] - r[0, 1]) / s
    elif r[0, 0] > r[1, 1] and r[0, 0] > r[2, 2]:
        s = math.sqrt(1.0 + r[0, 0] - r[1, 1] - r[2, 2]) * 2.0
        q[3] = (r[2, 1] - r[1, 2]) / s
        q[0] = 0.25 * s
        q[1] = (r[0, 1] + r[1, 0]) / s
        q[2] = (r[0, 2] + r[2, 0]) / s
    elif r[1, 1] > r[2, 2]:
        s = math.sqrt(1.0 + r[1, 1] - r[0, 0] - r[2, 2]) * 2.0
        q[3] = (r[0, 2] - r[2, 0]) / s
        q[0] = (r[0, 1] + r[1, 0]) / s
        q[1] = 0.25 * s
        q[2] = (r[1, 2] + r[2, 1]) / s
    else:
        s = math.sqrt(1.0 + r[2, 2] - r[0, 0] - r[1, 1]) * 2.0
        q[3] = (r[1, 0] - r[0, 1]) / s
        q[0] = (r[0, 2] + r[2, 0]) / s
        q[1] = (r[1, 2] + r[2, 1]) / s
        q[2] = 0.25 * s
    q /= np.linalg.norm(q)
    return q


def _fit_native_pose(path: Path, contract: dict[str, Any]) -> dict[str, Any]:
    """Append an explicit all-frame native type-2 rigid-particle fit."""

    if h5py is None or np is None:
        raise RuntimeError("v24 native pose fit requires the integration venv h5py/numpy")
    with h5py.File(path, "r+") as handle:
        initial_type = np.asarray(handle["initial_type"][:], dtype=np.int8)
        floating_idx = np.flatnonzero(initial_type == 2)
        if len(floating_idx) == 0:
            raise ValueError("native floating type2 cohort is empty")
        p0 = np.asarray(handle["position"][0, floating_idx, :], dtype=np.float64)
        center0 = np.asarray(contract["center_m"], dtype=np.float64)
        if not np.isfinite(p0).all():
            raise ValueError("native initial floating coordinates contain non-finite values")
        body0 = p0 - center0
        nframes = int(handle["position"].shape[0])
        fit_pos = np.empty((nframes, 3), dtype=np.float64)
        fit_q = np.empty((nframes, 4), dtype=np.float64)
        fit_r = np.empty((nframes, 3, 3), dtype=np.float64)
        rms = np.empty(nframes, dtype=np.float64)
        maxerr = np.empty(nframes, dtype=np.float64)
        center_offset = np.empty(nframes, dtype=np.float64)
        quat_angle = np.empty(nframes, dtype=np.float64)
        source_q = np.asarray(handle["rigid_body/orientation_quaternion"][:], dtype=np.float64)
        source_pos = np.asarray(handle["rigid_body/position"][:], dtype=np.float64)
        previous_q: np.ndarray | None = None
        for frame in range(nframes):
            observed = np.asarray(handle["position"][frame, floating_idx, :], dtype=np.float64)
            if not np.isfinite(observed).all():
                raise ValueError(f"native floating coordinates are not finite at frame {frame}")
            a = body0 - body0.mean(axis=0)
            b = observed - observed.mean(axis=0)
            u, _s, vt = np.linalg.svd(a.T @ b)
            rotation = vt.T @ u.T
            if np.linalg.det(rotation) < 0.0:
                vt[-1, :] *= -1.0
                rotation = vt.T @ u.T
            translation = np.mean(observed - body0 @ rotation.T, axis=0)
            predicted = body0 @ rotation.T + translation
            errors = np.linalg.norm(predicted - observed, axis=1)
            q = _quat_from_rotation(rotation)
            if previous_q is not None and float(np.dot(previous_q, q)) < 0.0:
                q = -q
            previous_q = q
            fit_pos[frame] = translation
            fit_q[frame] = q
            fit_r[frame] = rotation
            rms[frame] = float(np.sqrt(np.mean(errors * errors)))
            maxerr[frame] = float(np.max(errors))
            center_offset[frame] = float(np.linalg.norm(translation - source_pos[frame]))
            source_norm = float(np.linalg.norm(source_q[frame]))
            dot = abs(float(np.dot(q, source_q[frame] / source_norm))) if source_norm > 0.0 else float("nan")
            quat_angle[frame] = float(2.0 * math.acos(max(-1.0, min(1.0, dot)))) if math.isfinite(dot) else float("nan")
        group = handle["rigid_body"]
        for name in ("native_fit_position", "native_fit_quaternion_xyzw", "native_fit_rotation_matrix", "native_fit_residual_rms_m", "native_fit_residual_max_m", "native_fit_center_offset_m", "native_fit_quaternion_angle_vs_source_rad"):
            if name in group:
                del group[name]
        group.create_dataset("native_fit_position", data=fit_pos, dtype="f8")
        group.create_dataset("native_fit_quaternion_xyzw", data=fit_q, dtype="f8")
        group.create_dataset("native_fit_rotation_matrix", data=fit_r, dtype="f8")
        group.create_dataset("native_fit_residual_rms_m", data=rms, dtype="f8")
        group.create_dataset("native_fit_residual_max_m", data=maxerr, dtype="f8")
        group.create_dataset("native_fit_center_offset_m", data=center_offset, dtype="f8")
        group.create_dataset("native_fit_quaternion_angle_vs_source_rad", data=quat_angle, dtype="f8")
        group.attrs["native_fit_pose_semantics"] = "Kabsch fit of every finite type2 native particle against frame0 coordinates about generated XML center; source FloatingInfo arrays remain unchanged"
        group.attrs["native_fit_quaternion_convention"] = "xyzw, proper column-vector rotation, sign-continuous over saved frames"
        group.attrs["native_fit_frame"] = "world coordinates"
        group.attrs["native_fit_particle_count"] = int(len(floating_idx))
        group.attrs["native_fit_contract_center_m"] = json.dumps(center0.tolist(), separators=(",", ":"))
        group.attrs["native_fit_qa_status"] = "diagnostic_only; residual is measured, not threshold-relaxed"
    return {
        "particle_count": int(len(floating_idx)),
        "frames": nframes,
        "residual_rms_max_m": float(np.max(rms)),
        "residual_rms_q95_m": float(np.quantile(rms, 0.95)),
        "residual_max_max_m": float(np.max(maxerr)),
        "residual_max_q95_m": float(np.quantile(maxerr, 0.95)),
        "worst_residual_frame": int(np.argmax(maxerr)),
        "center_offset_max_m": float(np.max(center_offset)),
        "quaternion_angle_vs_source_max_rad": float(np.nanmax(quat_angle)),
        "fit_is_diagnostic_only": True,
        "source_pose_arrays_unchanged": True,
    }


def _run_enriched(args: argparse.Namespace) -> int:
    if h5py is None or np is None:
        raise RuntimeError("v24 conversion requires the integration venv h5py/numpy")
    data_dir = Path(args.data_dir).resolve()
    manifest = Path(args.manifest).resolve()
    generated_xml = Path(args.generated_xml).resolve()
    motion_csv = Path(args.motion_csv).resolve()
    output = Path(args.output).resolve()
    report_path = Path(args.report).resolve()
    V16._verify_tree(manifest, data_dir)
    contract = V20._contract_from_xml(generated_xml)
    report = V19.convert_sparse(case_id=str(args.case_id), data_dir=data_dir, generated_xml=generated_xml, motion_csv=motion_csv, output_h5=output, report_path=report_path)
    rigid_qa = V20._enrich_h5(output, contract)
    native_fit = _fit_native_pose(output, contract)
    report["schema"] = "ds02.f6.enriched-native-conversion-report.v2"
    report["rigid_contract"] = contract
    report["rigid_state_qa"] = rigid_qa
    report["native_particle_pose_fit"] = native_fit
    report["source_motion_csv"] = str(motion_csv)
    report["source_motion_csv_sha256"] = sha256(motion_csv)
    report["output_sha256"] = sha256(output)
    report["q_n_status"] = "pending_native_exclusion_reconciliation_and_pose_semantics"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    V16._verify_tree(manifest, data_dir)
    return 0


def _run_official(args: argparse.Namespace, *, floating: bool) -> int:
    data_dir = Path(args.data_dir).resolve()
    manifest = Path(args.manifest).resolve()
    output = Path(args.output_prefix).resolve()
    if floating:
        extra = ["-onlymk:60", "-savedata", "{output}", "-savemotion:1", "-csvsep:0"]
        binary = FLOATING_INFO
    else:
        extra = ["-filexml", str(Path(args.generated_xml).resolve()), "-onlymk:60", "-viscoauto", "-gravity:0:0:-9.81", "-momentin_xyz:2.4:1.2:1.08", "-momentex_xyz:2.4:1.2:1.08", "-savecsv", "{output}", "-threads:2", "-csvsep:0"]
        binary = COMPUTE_FORCES
    return V16._run_official_with_manifest(binary, data_dir, manifest, output, extra)


def _run_labels(args: argparse.Namespace) -> int:
    return V19._run_labels(args)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare-audits", "prepare-conversions", "prepare-labels", "run-floating-info", "run-compute-forces", "run-enriched-conversion", "run-labels"])
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output-prefix", type=Path)
    parser.add_argument("--case-id")
    parser.add_argument("--generated-xml", type=Path)
    parser.add_argument("--motion-csv", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    if args.action == "prepare-audits":
        print(json.dumps(prepare_audits(), ensure_ascii=False, indent=2))
        return 0
    if args.action == "prepare-conversions":
        print(json.dumps(prepare_conversions(), ensure_ascii=False, indent=2))
        return 0
    if args.action == "prepare-labels":
        print(json.dumps(prepare_labels(), ensure_ascii=False, indent=2))
        return 0
    if args.action == "run-floating-info":
        for name in ("data_dir", "manifest", "output_prefix"):
            if getattr(args, name) is None:
                parser.error(f"run-floating-info requires --{name.replace('_', '-')}")
        return _run_official(args, floating=True)
    if args.action == "run-compute-forces":
        for name in ("data_dir", "manifest", "output_prefix", "generated_xml"):
            if getattr(args, name) is None:
                parser.error(f"run-compute-forces requires --{name.replace('_', '-')}")
        return _run_official(args, floating=False)
    if args.action == "run-enriched-conversion":
        for name in ("case_id", "data_dir", "manifest", "generated_xml", "motion_csv", "output", "report"):
            if getattr(args, name) is None:
                parser.error(f"run-enriched-conversion requires --{name.replace('_', '-')}")
        return _run_enriched(args)
    for name in ("source", "config", "output"):
        if getattr(args, name) is None:
            parser.error(f"run-labels requires --{name}")
    return _run_labels(args)


if __name__ == "__main__":
    raise SystemExit(main())
