#!/usr/bin/env python3
"""Prepare, execute, and validate a shared F6 static/Kabsch H5 attempt.

This forward-only version is intentionally different from the consumed v1
join guard.  One worker opens each bound trajectory H5 once.  While that file
handle is open it audits the initial typed axes and streams the floating
particle positions through direct SO(3) Kabsch fits.  The shared v4 runtime
must hash both H5 paths before launch and after the worker returns, so a
separate static child cannot finish its pre/post window before Kabsch starts.

Preparation never hashes H5 contents.  It uses the immutable static request's
declared H5 digest and byte count; the actual guard performs the launch/end
hashes.  Physical fate, dynamics, QN, and QE remain UNKNOWN.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

try:
    import h5py
except ImportError:  # pragma: no cover - only needed by the guarded worker
    h5py = None


SCRIPT = Path(__file__).resolve()
WORKTREE_ROOT = SCRIPT.parents[2]
VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
STATIC_REQUEST_DEFAULT = SCRIPT.parents[1] / "campaigns/ds-data-02/stage2/requests/static-per-mk-h5-audit-f6-sentinels-v2.json"
RIGID_BINDING_DEFAULT = SCRIPT.parents[1] / "campaigns/ds-data-02/stage2/requests/f6-rigid-observation-v1/f6-rigid-observation-binding.json"
RIGID_REQUEST_DEFAULT = SCRIPT.parents[1] / "campaigns/ds-data-02/stage2/requests/f6-rigid-observation-v1/f6-rigid-observation-v1.json"
RUNTIME_V4_DEFAULT = SCRIPT.parent / "ds_data02_runtime_v4.py"
RUNTIME_V2_DEFAULT = SCRIPT.parent / "ds_data02_runtime_v2.py"
DISPATCH_V4_DEFAULT = SCRIPT.parent / "ds_data02_stage2_dispatch_v4.py"
STRICT_V4_DEFAULT = SCRIPT.parent / "ds_data02_strict_dispatch_v4.py"
CURRENT_DEFAULT = SCRIPT.parents[1] / "campaigns/ds-data-02/stage2/CURRENT336.json"
MATRIX_DEFAULT = SCRIPT.parents[1] / "campaigns/ds-data-02/stage2/review-source/SENTINEL_MATRIX.json"

EXPECTED = {
    "F6-S1": "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S095_DP025",
    "F6-S2": "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S200_DP025",
}
EXPECTED_IDS = tuple(EXPECTED.values())
STATIC_SCHEMA = "ds02.stage2.static-per-mk-h5-audit.v2"
OUTPUT_SCHEMA = "ds02.stage2.f6-static-kabsch-combined.v2"
BUNDLE_SCHEMA = "ds02.stage2.f6-static-kabsch-combined-bundle.v2"
REQUEST_CASE = "STAGE2_F6_STATIC_KABSCH_COMBINED_V2"
REQUEST_ATTEMPT = "f6-static-kabsch-combined-v2"
RIGID_SCHEMA = "ds02.stage2.f6-rigid-observation.v3"
RUNTIME_SHA_EXPECTED = "fa8e1ec4a95fb3927007a551dc15c9d762ecaaa72ae77f486457bc6d8d91f7b2"
SO3_RMSE_DEG = 2.0
SO3_MAX_DEG = 5.0
MASS_TOL_KG = 1.0e-6
TIME_TOL_S = 1.0e-6


class CombinedGuardError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise CombinedGuardError(f"{label} is missing: {path}")
    return path


def read_json(value: str | Path, label: str) -> tuple[Path, dict[str, Any]]:
    path = require_file(value, label)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CombinedGuardError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise CombinedGuardError(f"{label} is not a JSON object: {path}")
    return path, payload


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def actual_ref(path: str | Path, declared: str | None, label: str) -> dict[str, Any]:
    value = require_file(path, label)
    actual = sha256(value)
    if declared and actual != str(declared):
        raise CombinedGuardError(f"{label} digest differs: {value}")
    return {"path": str(value), "sha256": actual, "bytes": value.stat().st_size}


def path_from_flag(command: list[Any], flag: str, label: str) -> Path:
    for index, value in enumerate(command[:-1]):
        if str(value) == flag:
            return Path(str(command[index + 1])).expanduser().resolve()
    raise CombinedGuardError(f"{label} command lacks {flag}")


def static_h5_rows(static: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if static.get("attempt_id") != "static-per-mk-h5-audit-f6-sentinels-v2":
        raise CombinedGuardError("static request is not the frozen two-sentinel v2 request")
    paths = [Path(str(value)).resolve() for value in static.get("input_files", [])]
    digests = static.get("input_sha256", {})
    costs = static.get("source_read_cost", {}).get("trajectory_h5_bytes", {})
    rows: dict[str, dict[str, Any]] = {}
    for physical_id in EXPECTED_IDS:
        matches = [path for path in paths if path.name == "trajectory.h5" and physical_id in str(path)]
        if len(matches) != 1:
            raise CombinedGuardError(f"static request has {len(matches)} H5 matches for {physical_id}")
        h5_path = matches[0]
        declared = digests.get(str(h5_path))
        if not isinstance(declared, str) or len(declared) != 64:
            raise CombinedGuardError(f"static H5 digest is absent for {physical_id}")
        if not h5_path.is_file():
            raise CombinedGuardError(f"bound H5 is missing: {h5_path}")
        declared_bytes = int(costs.get(physical_id, -1))
        if declared_bytes <= 0 or h5_path.stat().st_size != declared_bytes:
            raise CombinedGuardError(f"static H5 byte declaration differs for {physical_id}: {h5_path}")
        conversion_matches = [path for path in paths if path.name == "conversion-report.json" and physical_id in str(path)]
        if len(conversion_matches) != 1:
            raise CombinedGuardError(f"static request has {len(conversion_matches)} conversion matches for {physical_id}")
        conversion_path = conversion_matches[0]
        conversion_digest = digests.get(str(conversion_path))
        if not isinstance(conversion_digest, str) or len(conversion_digest) != 64:
            raise CombinedGuardError(f"conversion digest is absent for {physical_id}")
        conversion = read_json(conversion_path, f"{physical_id} conversion report")[1]
        if conversion.get("conversion_status") != "completed":
            raise CombinedGuardError(f"conversion is not completed for {physical_id}")
        output_hdf5 = Path(str(conversion.get("output_hdf5", ""))).expanduser().resolve()
        if output_hdf5 != h5_path:
            raise CombinedGuardError(f"conversion output H5 differs for {physical_id}")
        if str(conversion.get("output_sha256")) != declared:
            raise CombinedGuardError(f"conversion output digest differs for {physical_id}")
        rows[physical_id] = {
            "trajectory_h5": {"path": str(h5_path), "sha256": declared, "bytes": declared_bytes},
            "conversion_report": actual_ref(conversion_path, conversion_digest, f"{physical_id} conversion report"),
            "conversion": conversion,
        }
    return rows


def small_binding(row: dict[str, Any], field: str, label: str) -> dict[str, Any]:
    digest_field = {
        "solver_receipt_path": "solver_receipt_sha256",
        "generated_xml_path": "generated_xml_sha256",
        "runparts_path": "runparts_sha256",
        "runout_path": "runout_sha256",
        "floating_csv_path": "floating_csv_sha256",
        "floating_report_path": "floating_report_sha256",
        "partfloatinfo_path": "partfloatinfo_sha256",
    }[field]
    digest = row.get(digest_field)
    if not isinstance(digest, str) or len(digest) != 64:
        raise CombinedGuardError(f"{label} has no declared digest")
    return actual_ref(row.get(field, ""), digest, label)


def input_digest_map(paths: list[Path]) -> dict[str, str]:
    unique = list(dict.fromkeys(str(Path(path).expanduser().resolve()) for path in paths))
    return {path: sha256(Path(path)) for path in unique}


def prepare(static_request_path: Path, rigid_binding_path: Path, rigid_request_path: Path,
            current_path: Path, matrix_path: Path, runtime_v4_path: Path,
            output_manifest: Path, output_request: Path) -> dict[str, Any]:
    static_path, static = read_json(static_request_path, "F6 static request")
    binding_path, binding = read_json(rigid_binding_path, "F6 rigid source binding")
    rigid_path, rigid_request = read_json(rigid_request_path, "F6 rigid request")
    current = require_file(current_path, "CURRENT336")
    matrix = require_file(matrix_path, "sentinel matrix")
    if binding.get("schema") != "ds02.stage2.f6-rigid-observation-binding.v1":
        raise CombinedGuardError("unexpected rigid binding schema")
    if set(binding.get("sentinels", {})) != {"F6-S1", "F6-S2"}:
        raise CombinedGuardError("rigid binding must contain exactly F6-S1/F6-S2")
    if rigid_request.get("case_id") != "STAGE2_F6_RIGID_OBSERVATION_SENTINELS":
        raise CombinedGuardError("unexpected rigid request")
    rigid_command = rigid_request.get("command", [])
    bound_current = path_from_flag(rigid_command, "--current", "rigid")
    bound_matrix = path_from_flag(rigid_command, "--sentinel-matrix", "rigid")
    if bound_current != current.resolve() or bound_matrix != matrix.resolve():
        raise CombinedGuardError("explicit CURRENT/matrix arguments differ from rigid request")
    rigid_inputs = {str(Path(path).resolve()): digest for path, digest in rigid_request.get("input_sha256", {}).items()}
    for path, label in ((current, "CURRENT336"), (matrix, "sentinel matrix")):
        if rigid_inputs.get(str(path.resolve())) != sha256(path):
            raise CombinedGuardError(f"{label} is not bound by the rigid request")
    h5_rows = static_h5_rows(static)
    source_cases: list[dict[str, Any]] = []
    for sentinel_id in ("F6-S1", "F6-S2"):
        physical_id = EXPECTED[sentinel_id]
        row = binding["sentinels"][sentinel_id]
        if row.get("physical_case_id") != physical_id:
            raise CombinedGuardError(f"{sentinel_id} physical identity differs")
        small = {
            key: small_binding(row, key, f"{sentinel_id} {key}")
            for key in ("solver_receipt_path", "generated_xml_path", "runparts_path",
                        "runout_path", "floating_csv_path", "floating_report_path",
                        "partfloatinfo_path")
        }
        solver_path = Path(small["solver_receipt_path"]["path"])
        solver = read_json(solver_path, f"{sentinel_id} solver receipt")[1]
        if solver.get("schema") != "ds02.execution-receipt.v1" or solver.get("status") != "completed" or solver.get("returncode") != 0:
            raise CombinedGuardError(f"{sentinel_id} solver receipt is not completed code 0")
        request = solver.get("request", {})
        if request.get("family_id") != "F6" or request.get("physical_case_id") != physical_id:
            raise CombinedGuardError(f"{sentinel_id} solver receipt identity differs")
        conversion = h5_rows[physical_id]["conversion"]
        provenance = conversion.get("source_provenance", {})
        provenance_receipt = provenance.get("solver_receipt", {})
        if str(provenance_receipt.get("path", "")).strip() != str(solver_path):
            raise CombinedGuardError(f"{sentinel_id} conversion raw solver receipt differs")
        if str(provenance_receipt.get("sha256", "")) != small["solver_receipt_path"]["sha256"]:
            raise CombinedGuardError(f"{sentinel_id} conversion raw solver receipt digest differs")
        source_cases.append({
            "sentinel_id": sentinel_id,
            "physical_case_id": physical_id,
            "trajectory_h5": h5_rows[physical_id]["trajectory_h5"],
            "conversion_report": h5_rows[physical_id]["conversion_report"],
            "small_sources": small,
            "solver_receipt": small["solver_receipt_path"],
            "raw_solver_output_root": str(Path(str(provenance.get("data_root", ""))).expanduser().resolve()),
        })
    h5_total = sum(int(row["trajectory_h5"]["bytes"]) for row in source_cases)
    runtime_v4 = actual_ref(runtime_v4_path, None, "Stage2 v4 runtime")
    runtime_v2 = actual_ref(RUNTIME_V2_DEFAULT, None, "Stage2 v2 runtime")
    dispatch_v4 = actual_ref(DISPATCH_V4_DEFAULT, None, "Stage2 v4 dispatch")
    strict_v4 = actual_ref(STRICT_V4_DEFAULT, None, "Stage2 strict v4 dispatch")
    source_files = [SCRIPT, VENV, static_path, binding_path, rigid_path, current, matrix,
                    Path(runtime_v4["path"]), Path(runtime_v2["path"]),
                    Path(dispatch_v4["path"]), Path(strict_v4["path"]),
                    SCRIPT.parent / "ds_data02_stage2_f6_rigid_observation_v3.py"]
    for row in source_cases:
        source_files.append(Path(row["conversion_report"]["path"]))
        source_files.extend(Path(value["path"]) for value in row["small_sources"].values())
    source_files = list(dict.fromkeys(Path(path).resolve() for path in source_files))
    # H5 content is never read here.  The static request already owns its
    # declared digest; the combined guard request places both paths in the
    # runtime's pre/post input set.
    input_hashes = input_digest_map([path for path in source_files
                                     if path not in {Path(row["trajectory_h5"]["path"]) for row in source_cases}])
    for row in source_cases:
        input_hashes[row["trajectory_h5"]["path"]] = row["trajectory_h5"]["sha256"]
    manifest = {
        "schema": BUNDLE_SCHEMA,
        "status": "PREPARED_COMBINED_H5_SOURCE_BOUND",
        "selected_case_ids": list(EXPECTED_IDS),
        "static_request": {"path": str(static_path), "sha256": sha256(static_path), "attempt_id": static["attempt_id"]},
        "rigid_binding": {"path": str(binding_path), "sha256": sha256(binding_path), "schema": binding["schema"]},
        "rigid_request": {"path": str(rigid_path), "sha256": sha256(rigid_path), "case_id": rigid_request["case_id"]},
        "current": {"path": str(current), "sha256": sha256(current)},
        "sentinel_matrix": {"path": str(matrix), "sha256": sha256(matrix)},
        "runtime_binding": runtime_v4,
        "source_cases": source_cases,
        "hash_ownership": {
            "owner": "single_combined_v4_attempt",
            "h5_hash_pre_bytes": h5_total,
            "h5_hash_post_bytes": h5_total,
            "h5_hash_pre_post_bytes": h5_total * 2,
            "h5_paths_registered_once": True,
            "static_and_kabsch_share_same_h5_open": True,
            "child_static_pre_post_forbidden": True,
            "kabsch_h5_read_required": True,
            "h5_content_hashed_during_prepare": False,
        },
        "execution_contract": {
            "one_open_per_h5": True,
            "static_initial_datasets_and_floating_frames_same_handle": True,
            "kabsch_source": "direct SO(3) from H5 type=2 (Zone,Idp) positions",
            "snapshot_json_written": False,
            "observer_semantics": "UNKNOWN unless source-bound producer contract supplies it",
            "so3_tolerances_deg": {"rmse": SO3_RMSE_DEG, "max": SO3_MAX_DEG},
            "body_mass_kg": 128.0,
            "support_sample_mass_kg": 256.0,
        },
        "preparation_policy": {"h5_opened": False, "solver_started": False, "kabsch_started": False},
    }
    manifest["guard_input_files"] = sorted(input_hashes)
    atomic_json(output_manifest, manifest)
    manifest_sha = sha256(output_manifest)
    input_hashes[str(output_manifest.resolve())] = manifest_sha
    command = [
        str(VENV), str(SCRIPT), "run", "--manifest", str(output_manifest.resolve()),
        "--output", "{attempt_root}/f6-static-kabsch-combined.json",
    ]
    request = {
        "schema": "ds02.request.v1",
        "family_id": "F6",
        "case_id": REQUEST_CASE,
        "attempt_id": REQUEST_ATTEMPT,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 1800,
        "estimated_storage_bytes": 256 * 1024 * 1024,
        "cwd": str(SCRIPT.parent),
        "worktree_root": str(WORKTREE_ROOT),
        "command": command,
        "input_files": sorted(input_hashes),
        "input_sha256": dict(sorted(input_hashes.items())),
        "runtime_binding": runtime_v4,
        "source_policy": {
            "h5_read_by_worker": True,
            "h5_hash_by_runtime_pre_post": True,
            "h5_hash_by_prepare": False,
            "h5_hash_owner": "single_combined_v4_attempt",
            "static_and_kabsch_same_attempt": True,
            "snapshot_json": "not written; in-process frame stream",
        },
        "source_cases": [{
            "sentinel_id": row["sentinel_id"],
            "physical_case_id": row["physical_case_id"],
            "trajectory_h5_path": row["trajectory_h5"]["path"],
            "trajectory_h5_sha256": row["trajectory_h5"]["sha256"],
            "trajectory_h5_bytes": row["trajectory_h5"]["bytes"],
        } for row in source_cases],
        "source_read_cost": {
            "h5_total_bytes": h5_total,
            "runtime_pre_post_hash_bytes": h5_total * 2,
            "worker_frame_reads": "all time/valid/position rows for type=2 support samples; no duplicate child",
            "output_json_estimate_bytes": 256 * 1024 * 1024,
        },
        "canonical_ready": True,
        "launch_owner": "root",
        "primary_launch_owner": "root",
        "launch": True,
        "launch_allowed": True,
        "execution_allowed": True,
        "foreign_process_protection_required": True,
        "shared_lease_required": True,
        "physical_fate": "UNKNOWN",
        "dynamical_impact": "UNKNOWN",
        "QN": "NOT_ASSESSED",
        "QE": "NOT_ASSESSED",
        "request_note": (
            "Single shared H5 attempt: runtime v4 registers both H5 files once and hashes "
            "each before launch and after worker completion. The worker opens each H5 once, "
            "performs static initial-MK mass reconciliation and direct Kabsch frame fits "
            "through the same handle. Existing v1 no-H5 join remains immutable and is not "
            "a substitute for this request."
        ),
    }
    atomic_json(output_request, request)
    return {
        "status": "prepared",
        "bundle": str(output_manifest.resolve()),
        "bundle_sha256": manifest_sha,
        "request": str(output_request.resolve()),
        "request_sha256": sha256(output_request),
        "h5_pre_post_hash_bytes": h5_total * 2,
        "input_count": len(input_hashes),
    }


def fluid_blocks(conversion: dict[str, Any]) -> list[dict[str, int]]:
    result = []
    for raw in conversion.get("typed_identity", {}).get("blocks", []):
        if raw.get("tag") == "fluid" and int(raw.get("type", -1)) == 3:
            result.append({
                "begin": int(raw["begin"]), "count": int(raw["count"]),
                "mk": int(raw["mk"]), "type": int(raw["type"]),
            })
    if not result:
        raise CombinedGuardError("conversion report lacks type=3 fluid blocks")
    return result


def all_typed_blocks(conversion: dict[str, Any]) -> list[dict[str, int]]:
    result = []
    for raw in conversion.get("typed_identity", {}).get("blocks", []):
        result.append({
            "begin": int(raw["begin"]), "count": int(raw["count"]),
            "mk": int(raw["mk"]), "type": int(raw["type"]),
        })
    if not result:
        raise CombinedGuardError("conversion report lacks typed blocks")
    return result


def weighted_kabsch(initial: np.ndarray, current: np.ndarray, weights: np.ndarray) -> dict[str, Any]:
    if initial.shape != current.shape or initial.ndim != 2 or initial.shape[1] != 3:
        raise CombinedGuardError("Kabsch positions have incompatible shape")
    if weights.shape != (initial.shape[0],) or initial.shape[0] < 3:
        raise CombinedGuardError("Kabsch support has too few particles")
    if not np.isfinite(initial).all() or not np.isfinite(current).all() or not np.isfinite(weights).all() or np.any(weights <= 0):
        raise CombinedGuardError("Kabsch input is nonfinite or nonpositive")
    total = float(weights.sum(dtype=np.float64))
    xbar = (initial * weights[:, None]).sum(axis=0, dtype=np.float64) / total
    ybar = (current * weights[:, None]).sum(axis=0, dtype=np.float64) / total
    xc = initial - xbar
    yc = current - ybar
    covariance = xc.T @ (weights[:, None] * yc)
    u, singular, vt = np.linalg.svd(covariance)
    if singular[0] <= 0 or singular[-1] / singular[0] <= 1.0e-8:
        raise CombinedGuardError("Kabsch support geometry is rank-degenerate")
    rotation = vt.T @ u.T
    reflection = False
    if float(np.linalg.det(rotation)) < 0:
        vt[-1, :] *= -1
        rotation = vt.T @ u.T
        reflection = True
    predicted = xc @ rotation.T
    residual = predicted - yc
    norms = np.linalg.norm(residual, axis=1)
    return {
        "rotation_world_from_initial": rotation.tolist(),
        "determinant": float(np.linalg.det(rotation)),
        "residual_rmse_m": float(math.sqrt(float(np.sum(weights * norms * norms, dtype=np.float64)) / total)),
        "residual_max_m": float(np.max(norms)),
        "sample_centroid_current_m": ybar.tolist(),
        "reflection_correction_applied": reflection,
        "singular_values": singular.tolist(),
        "rank_relative": float(singular[-1] / singular[0]),
    }


def observer_rows(path: Path) -> list[dict[str, Any]]:
    required = {"part", "time [s]", "center.x [m]", "center.y [m]", "center.z [m]",
                "fomega.x [rad/s]", "fomega.y [rad/s]", "fomega.z [rad/s]"}
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter=";")
        fields = {str(item).strip() for item in (reader.fieldnames or [])}
        if not required <= fields:
            raise CombinedGuardError(f"FloatingInfo lacks fields {sorted(required - fields)}")
        result = []
        for ordinal, raw in enumerate(reader):
            item = {str(k).strip(): (v or "").strip() for k, v in raw.items() if k is not None}
            try:
                row = {
                    "part": int(item["part"]),
                    "time_s": float(item["time [s]"]),
                    "center_m": [float(item[f"center.{axis} [m]"]) for axis in "xyz"],
                    "omega_rad_s": [float(item[f"fomega.{axis} [rad/s]"]) for axis in "xyz"],
                }
            except (KeyError, TypeError, ValueError) as exc:
                raise CombinedGuardError(f"FloatingInfo row {ordinal} is invalid") from exc
            if row["part"] != ordinal or not all(math.isfinite(value) for value in (*row["center_m"], *row["omega_rad_s"])):
                raise CombinedGuardError(f"FloatingInfo row {ordinal} identity/value is invalid")
            result.append(row)
    if not result:
        raise CombinedGuardError("FloatingInfo has no rows")
    return result


def _typed_static(h5: Any, physical_id: str, conversion: dict[str, Any],
                  h5_binding: dict[str, Any]) -> tuple[dict[str, Any], np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    required = ("particle_id", "particle_zone", "initial_type", "initial_mk", "initial_mass")
    missing = [name for name in required if name not in h5]
    if missing:
        raise CombinedGuardError(f"{physical_id} H5 lacks static datasets {missing}")
    ids = np.asarray(h5["particle_id"][:])
    zones = np.asarray(h5["particle_zone"][:])
    types = np.asarray(h5["initial_type"][:])
    mks = np.asarray(h5["initial_mk"][:])
    masses = np.asarray(h5["initial_mass"][:], dtype=np.float64)
    if len({len(ids), len(zones), len(types), len(mks), len(masses)}) != 1:
        raise CombinedGuardError(f"{physical_id} static axes differ")
    if len(np.unique(ids)) != len(ids) or not np.isfinite(masses).all() or np.any(masses <= 0):
        raise CombinedGuardError(f"{physical_id} static IDs/masses invalid")
    blocks = all_typed_blocks(conversion)
    expected_type = np.full(len(ids), -1, dtype=np.int16)
    expected_mk = np.full(len(ids), -1, dtype=np.int32)
    for block in blocks:
        begin, end = block["begin"], block["begin"] + block["count"]
        if begin < 0 or end > len(ids):
            raise CombinedGuardError(f"{physical_id} typed block exceeds H5 axis")
        expected_type[begin:end] = block["type"]
        expected_mk[begin:end] = block["mk"]
    if not np.array_equal(types, expected_type) or not np.array_equal(mks, expected_mk):
        raise CombinedGuardError(f"{physical_id} H5 typed axes differ from conversion blocks")
    fluid = types == 3
    fluid_blocks_rows = fluid_blocks(conversion)
    expected_fluid = sum(row["count"] for row in fluid_blocks_rows)
    if int(fluid.sum()) != expected_fluid:
        raise CombinedGuardError(f"{physical_id} fluid count differs from conversion")
    mass_min = float(conversion["typed_identity"]["initial_mass_min_kg"])
    mass_max = float(conversion["typed_identity"]["initial_mass_max_kg"])
    if not math.isclose(float(masses[fluid].min()), mass_min, abs_tol=1.0e-12, rel_tol=0):
        raise CombinedGuardError(f"{physical_id} minimum fluid mass differs")
    if not math.isclose(float(masses[fluid].max()), mass_max, abs_tol=1.0e-12, rel_tol=0):
        raise CombinedGuardError(f"{physical_id} maximum fluid mass differs")
    per_mk = []
    for mk in sorted(set(int(v) for v in mks[fluid])):
        mask = fluid & (mks == mk)
        values = masses[mask]
        per_mk.append({
            "mk": mk, "count": int(mask.sum()),
            "mass_sum_kg": float(values.sum(dtype=np.float64)),
            "mass_min_kg": float(values.min()), "mass_max_kg": float(values.max()),
        })
    support = types == 2
    support_mass = float(masses[support].sum(dtype=np.float64))
    if not math.isclose(support_mass, 256.0, abs_tol=MASS_TOL_KG, rel_tol=0):
        raise CombinedGuardError(f"{physical_id} support sample mass is not 256 kg: {support_mass}")
    identity_pairs = np.column_stack((zones.astype("<i8"), ids.astype("<i8")))
    identity_digest = hashlib.sha256(identity_pairs.tobytes(order="C")).hexdigest()
    static = {
        "status": "STATIC_PER_MK_MASS_RECONCILED",
        "trajectory": {
            **h5_binding, "h5_opened": True, "frame_datasets_read": True,
            "datasets_read": ["particle_id", "particle_zone", "initial_type", "initial_mk", "initial_mass", "time", "valid", "position"],
        },
        "particle_count": int(len(ids)), "fluid_particle_count": int(fluid.sum()),
        "particle_identity": {
            "key": "(Zone,Idp)", "axis_order_constant": True,
            "zone_idp_order_sha256": identity_digest,
        },
        "fluid_mass_kg": float(masses[fluid].sum(dtype=np.float64)),
        "floating_support_particle_count": int(support.sum()),
        "floating_support_mass_kg": support_mass,
        "conversion_fluid_blocks": fluid_blocks_rows,
        "per_mk": per_mk,
        "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN",
    }
    return static, ids, zones, types, masses


def direct_case(row: dict[str, Any]) -> dict[str, Any]:
    if h5py is None:
        raise CombinedGuardError("h5py is required in the guarded worker")
    physical_id = row["physical_case_id"]
    h5_binding = row["trajectory_h5"]
    conversion = row["conversion"]
    floating_csv = Path(row["small_sources"]["floating_csv_path"]["path"])
    observer = observer_rows(floating_csv)
    h5_path = Path(h5_binding["path"])
    with h5py.File(h5_path, "r") as h5:
        static, ids, zones, types, masses = _typed_static(h5, physical_id, conversion, h5_binding)
        for name in ("time", "valid", "position"):
            if name not in h5:
                raise CombinedGuardError(f"{physical_id} H5 lacks frame dataset {name}")
        time_ds, valid_ds, position_ds = h5["time"], h5["valid"], h5["position"]
        nframes = int(time_ds.shape[0])
        if nframes != len(observer):
            raise CombinedGuardError(f"{physical_id} H5 frames differ from FloatingInfo rows")
        support_indices = np.flatnonzero(types == 2)
        if len(support_indices) != 16384:
            raise CombinedGuardError(f"{physical_id} support sample count differs: {len(support_indices)}")
        initial_valid = np.asarray(valid_ds[0, support_indices], dtype=bool)
        initial = np.asarray(position_ds[0, support_indices, :], dtype=np.float64)
        if not bool(initial_valid.all()) or not np.isfinite(initial).all():
            raise CombinedGuardError(f"{physical_id} initial floating support is not fully valid")
        frames = []
        last_time = -math.inf
        for index in range(nframes):
            time_s = float(time_ds[index])
            if not math.isfinite(time_s) or time_s <= last_time:
                raise CombinedGuardError(f"{physical_id} H5 frame times are invalid at {index}")
            last_time = time_s
            valid = np.asarray(valid_ds[index, support_indices], dtype=bool)
            current = np.asarray(position_ds[index, support_indices, :], dtype=np.float64)
            if not bool(valid.all()) or not np.isfinite(current).all():
                raise CombinedGuardError(f"{physical_id} floating support is invalid at frame {index}")
            fit = weighted_kabsch(initial, current, masses[support_indices])
            frames.append({
                "part": index, "time_s": time_s,
                **fit,
                "identity_order_changed": False,
                "observer_center_m": observer[index]["center_m"],
                "observer_omega_rad_s": observer[index]["omega_rad_s"],
                "observer_center_frame": "UNKNOWN",
                "observer_angular_velocity_frame": "UNKNOWN",
            })
        if abs(frames[0]["residual_rmse_m"]) > 1.0e-7:
            raise CombinedGuardError(f"{physical_id} initial Kabsch pose is not identity-support")
    return {
        "sentinel_id": row["sentinel_id"], "physical_case_id": physical_id,
        "static": static,
        "kabsch": {
            "status": "completed", "source": "direct H5 position dataset in same open as static audit",
            "frame_count": len(frames), "support_particle_count": 16384,
            "support_sample_mass_kg": static["floating_support_mass_kg"],
            "particle_identity": static["particle_identity"],
            "frames": frames,
            "frozen_contract": {
                "so3_error_tolerances_deg": {"rmse": SO3_RMSE_DEG, "max": SO3_MAX_DEG},
                "orientation_source": "direct proper Kabsch from same (Zone,Idp) positions",
                "rotation_convention": "active column-vector world-from-initial; row positions transformed by R.T",
                "observer_center_frame": "UNKNOWN",
                "observer_angular_velocity_frame": "UNKNOWN",
                "body_mass_kg": 128.0, "support_sample_mass_kg": static["floating_support_mass_kg"],
            },
        },
        "h5_read_ledger": {
            "opened_once": True, "closed_after_static_and_kabsch": True,
            "trajectory_path": h5_binding["path"], "declared_sha256": h5_binding["sha256"],
            "declared_bytes": h5_binding["bytes"], "runtime_pre_post_hash_required": True,
        },
        "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN",
    }


def run(manifest_path: Path, output: Path) -> dict[str, Any]:
    manifest_path, bundle = read_json(manifest_path, "combined F6 bundle")
    if bundle.get("schema") != BUNDLE_SCHEMA or bundle.get("status") != "PREPARED_COMBINED_H5_SOURCE_BOUND":
        raise CombinedGuardError("combined bundle is not prepared")
    if bundle.get("hash_ownership", {}).get("static_and_kabsch_share_same_h5_open") is not True:
        raise CombinedGuardError("bundle does not require shared H5 open")
    results = [direct_case(row) for row in bundle.get("source_cases", [])]
    if {row["physical_case_id"] for row in results} != set(EXPECTED_IDS):
        raise CombinedGuardError("combined worker did not cover both sentinels")
    result = {
        "schema": OUTPUT_SCHEMA, "status": "completed",
        "bundle": {"path": str(manifest_path.resolve()), "sha256": sha256(manifest_path)},
        "cases": results,
        "runtime_binding_expected": bundle["runtime_binding"],
        "h5_hash_coverage": bundle["hash_ownership"],
        "source_policy": {
            "h5_opened": True, "h5_open_mode": "one_handle_per_case_shared_static_and_kabsch",
            "h5_rehashed_by_worker": False, "h5_pre_post_owner": "shared_runtime_v4",
            "snapshot_json_written": False, "solver_started": False, "cfd_or_model_run": False,
        },
        "qualification": {"physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED"},
    }
    atomic_json(output, result)
    return result


def validate(manifest_path: Path, output_path: Path, receipt_path: Path) -> dict[str, Any]:
    manifest_path, bundle = read_json(manifest_path, "combined F6 bundle")
    output_path, result = read_json(output_path, "combined F6 output")
    receipt_path, receipt = read_json(receipt_path, "combined execution receipt")
    if bundle.get("schema") != BUNDLE_SCHEMA or result.get("schema") != OUTPUT_SCHEMA:
        raise CombinedGuardError("combined schema mismatch")
    if result.get("status") != "completed" or receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise CombinedGuardError("combined output/receipt is not completed code 0")
    runtime = bundle["runtime_binding"]
    if receipt.get("runner_source") != runtime["path"] or receipt.get("runner_sha256") != runtime["sha256"]:
        raise CombinedGuardError("execution receipt is not from bound Stage2 v4 runtime")
    request = receipt.get("request", {})
    input_files = {str(Path(path).resolve()) for path in request.get("input_files", [])}
    declared = request.get("input_sha256", {})
    launch = receipt.get("input_hashes_at_launch", {})
    finish = receipt.get("input_hashes_after_run", {})
    expected_files = set(str(Path(path).resolve()) for path in bundle.get("guard_input_files", []))
    expected_files.add(str(manifest_path.resolve()))
    if not expected_files <= input_files:
        raise CombinedGuardError("runtime request omits a manifest/source input")
    for key in expected_files:
        expected = declared.get(key)
        if not expected or launch.get(key) != expected or finish.get(key) != expected:
            raise CombinedGuardError(f"runtime receipt lacks stable source input binding: {key}")
    for row in bundle["source_cases"]:
        h5 = row["trajectory_h5"]
        key = str(Path(h5["path"]).resolve())
        if key not in input_files or declared.get(key) != h5["sha256"] or launch.get(key) != h5["sha256"] or finish.get(key) != h5["sha256"]:
            raise CombinedGuardError(f"runtime receipt lacks stable pre/post binding for H5: {key}")
    if not input_files:
        raise CombinedGuardError("receipt input set is empty")
    by_id = {row.get("physical_case_id"): row for row in result.get("cases", [])}
    if set(by_id) != set(EXPECTED_IDS):
        raise CombinedGuardError("combined output has the wrong case union")
    for row in result["cases"]:
        if row.get("h5_read_ledger", {}).get("opened_once") is not True:
            raise CombinedGuardError(f"{row.get('physical_case_id')} lacks one-open ledger")
        if row.get("static", {}).get("trajectory", {}).get("frame_datasets_read") is not True:
            raise CombinedGuardError(f"{row.get('physical_case_id')} did not record frame reads")
        if row.get("kabsch", {}).get("status") != "completed":
            raise CombinedGuardError(f"{row.get('physical_case_id')} lacks Kabsch result")
        if row.get("kabsch", {}).get("frozen_contract", {}).get("so3_error_tolerances_deg") != {"rmse": SO3_RMSE_DEG, "max": SO3_MAX_DEG}:
            raise CombinedGuardError("SO3 tolerance contract differs")
    checked = {
        "schema": "ds02.stage2.f6-static-kabsch-combined-validation.v2",
        "status": "completed",
        "manifest": {"path": str(manifest_path), "sha256": sha256(manifest_path)},
        "output": {"path": str(output_path), "sha256": sha256(output_path)},
        "execution_receipt": {"path": str(receipt_path), "sha256": sha256(receipt_path)},
        "runtime_h5_pre_post_verified": True,
        "cases": sorted(by_id),
        "source_policy": {"h5_opened": True, "shared_attempt": True, "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN"},
    }
    return checked


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--static-request", type=Path, default=STATIC_REQUEST_DEFAULT)
    prep.add_argument("--rigid-binding", type=Path, default=RIGID_BINDING_DEFAULT)
    prep.add_argument("--rigid-request", type=Path, default=RIGID_REQUEST_DEFAULT)
    prep.add_argument("--current", type=Path, default=CURRENT_DEFAULT)
    prep.add_argument("--sentinel-matrix", type=Path, default=MATRIX_DEFAULT)
    prep.add_argument("--runtime-v4", type=Path, default=RUNTIME_V4_DEFAULT)
    prep.add_argument("--output-manifest", type=Path, required=True)
    prep.add_argument("--output-request", type=Path, required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--manifest", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    check = sub.add_parser("validate")
    check.add_argument("--manifest", type=Path, required=True)
    check.add_argument("--output", type=Path, required=True)
    check.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            result = prepare(args.static_request, args.rigid_binding, args.rigid_request, args.current,
                             args.sentinel_matrix, args.runtime_v4, args.output_manifest, args.output_request)
        elif args.action == "run":
            result = run(args.manifest, args.output)
        else:
            result = validate(args.manifest, args.output, args.receipt)
    except CombinedGuardError as exc:
        raise SystemExit(f"CombinedGuardError: {exc}")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
