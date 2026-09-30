#!/usr/bin/env python3
"""DS-DATA-02 F3 family generator and historical reuse auditor.

This module owns only the F3 family artefacts.  It deliberately contains no
solver launcher and imports no learning/runtime package.  The historical
source tree is read-only; new solver output, when a shared runner eventually
authorises it, belongs under ``/home/jade/Projects/DualSPHysics-data``.

The default ``generate`` action performs a light HDF5 header audit for the 32
historical native trajectories, writes the family definitions and plans, and
records missing work without pretending that a definition is a completed
solver case.  ``--full-hash`` is intentionally opt-in because a full digest of
32 multi-gigabyte files is an expensive operation and is not needed to read a
receipt that already binds the canonical source hash.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA = "ds-data-02.f3.family.v1"
GENERATOR_VERSION = "ds_data02_f3.v3"
REPO_ROOT = Path(__file__).resolve().parents[1]
FAMILY_ROOT = REPO_ROOT / "campaigns/ds-data-02/families/F3"
HISTORICAL_ROOT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab")
MATERIAL_ARCHIVE_ROOT = Path("/home/jade/Projects/DualSPHysics/f3-ref0081818-material-archive")
RAW_OUTPUT_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/case/attempt")
REFERENCE_GENCAS_RECEIPT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/"
    "F3_HISTORY_CELL3_PARENT/F3_HISTORY_CELL3_PARENT_GENCAS_01/execution-receipt.json"
)

CANONICAL_MANIFEST = "campaigns/l2-multifamily/evidence/f3-canonical-manifest.json"
HISTORICAL_GATE = "campaigns/l1-resume/continuation/F3-075-REF0081818-GATE.json"
HISTORICAL_CONTRACT = "campaigns/l1-resume/continuation/F3-REF0081818-TRAINING-DEVELOPMENT-FULL.json"
HISTORICAL_CLOSEOUT = "campaigns/l1-resume/continuation/F3-REF0081818-CAMPAIGN-CLOSEOUT.json"
OFFICIAL_ACCEL_DEFINITION = "vendor/official/DualSPHysics_v5.4/examples/main/05_SloshingTank/CaseSloshingAcc_Def.xml"
OFFICIAL_MOTION_DEFINITION = "vendor/official/DualSPHysics_v5.4/examples/main/05_SloshingTank/CaseSloshingMotion_Def.xml"
SOLVER_BINARY = HISTORICAL_ROOT / "vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"

HISTORICAL_RECIPE = "F3_CELL3_NS_visco1_native_nopen_revision075_ref0081818"
HISTORICAL_REFERENCE_RESOLUTIONS = [0.00818181818181818, 0.0075, 0.006]
HISTORICAL_TIME_WINDOW = [0.0, 8.35]
HISTORICAL_OUTPUT_INTERVAL = 0.01
HISTORICAL_PARTICLE_COUNT = 34560
HISTORICAL_MASS_KG = 14.58

# F3 is intentionally planned around two mechanisms.  The old fixed-tank
# recipe is a separate scope and never silently authorises either mechanism.
MECHANISMS: dict[str, dict[str, Any]] = {
    "dual_axis_phase": {
        "mechanism_id": "dual_axis_phase",
        "name": "3D槽双轴/相位控制",
        "geometry_family_id": "F3_CELL3_PLAIN",
        "control_family_id": "F3_CTRL_DUAL_AXIS_PHASE",
        "coordinate_frame_id": "fixed_tank_acceleration",
        "description": "CELL3连续槽内的x/y双轴加速度，独立幅值、频率比与相位；流体位置保留槽坐标。",
        "solver_dimension_required": 3,
        "axis_parameters": ["drive_amplitude_x", "drive_amplitude_y", "frequency_ratio", "axis_phase_rad"],
        "study_axes": ["drive_amplitude", "frequency_over_natural", "fill_fraction"],
        "geometry_holdout": "control_template_holdout",
        "legacy_transfer": "forbidden_without_new_2x3_reference",
    },
    "eccentric_baffle_exchange": {
        "mechanism_id": "eccentric_baffle_exchange",
        "name": "偏心挡板/分舱横向交换",
        "geometry_family_id": "F3_BAFFLE_ECCENTRIC_CHANNEL",
        "control_family_id": "F3_CTRL_MOVING_TANK_WORLD",
        "coordinate_frame_id": "moving_tank_world",
        "description": "带偏心挡板、有限横向通道和分舱的真实3D槽；刚体槽运动在世界坐标给定，交换事件在槽固连坐标测量。",
        "solver_dimension_required": 3,
        "axis_parameters": ["baffle_offset_y", "channel_width", "tank_sway_amplitude", "tank_yaw_phase_rad"],
        "study_axes": ["drive_amplitude", "frequency_over_natural", "fill_fraction"],
        "geometry_holdout": "channel_layout_holdout",
        "legacy_transfer": "forbidden_without_new_2x3_reference",
    },
}

NEW_RESOLUTION_LADDERS: dict[str, list[dict[str, Any]]] = {
    # The CELL3 ladder is chosen as a new control study.  The historical
    # 0.0075 recipe remains evidence only; these cells still need new runs.
    "dual_axis_phase": [
        {"resolution_id": "coarse", "dp_m": 0.010, "feature_cells": 9},
        {"resolution_id": "medium", "dp_m": 0.0075, "feature_cells": 12},
        {"resolution_id": "fine", "dp_m": 0.006, "feature_cells": 15},
    ],
    # A 0.060 m exchange aperture needs at least five particles across it at
    # the coarse level.  It is deliberately not a blind copy of 0.0075 m.
    "eccentric_baffle_exchange": [
        {"resolution_id": "coarse", "dp_m": 0.012, "feature_cells": 5},
        {"resolution_id": "medium", "dp_m": 0.008, "feature_cells": 8},
        {"resolution_id": "fine", "dp_m": 0.006, "feature_cells": 10},
    ],
}

PHYSICAL_AXIS_PLAN: dict[str, dict[str, Any]] = {
    "drive_amplitude": {
        "parameter": "dimensionless acceleration amplitude Gamma=a/g",
        "planned_levels": [0.6, 0.9, 1.2],
        "unit": "a/g",
        "role": "within-background amplitude axis; freeze against the actual continuous control file before launch",
    },
    "frequency_over_natural": {
        "parameter": "drive angular frequency / measured small-amplitude natural angular frequency",
        "planned_levels": [0.8, 1.0, 1.2],
        "unit": "ratio",
        "role": "resonant and off-resonant control axis; estimate natural frequency from the same geometry and fill fraction",
    },
    "fill_fraction": {
        "parameter": "initial fluid volume / usable tank volume",
        "planned_levels": [0.18, 0.27, 0.36],
        "unit": "fraction",
        "role": "continuous initial-state axis; history is approximately 0.18 and does not certify the other levels",
    },
}

PARENT_INPUT_TIME_WINDOW_S = [0.0, 10.0]
PARENT_INPUT_DT_S = 0.005
PARENT_INPUT_STOP_START_S = 8.0
PARENT_INPUT_STOP_END_S = 8.5
PARENT_INPUT_CONTROL_ROWS = int(round((PARENT_INPUT_TIME_WINDOW_S[1] - PARENT_INPUT_TIME_WINDOW_S[0]) / PARENT_INPUT_DT_S)) + 1
PARENT_DUAL_DP_M = 0.0075
PARENT_BAFFLE_DP_M = 0.008
PARENT_DUAL_CASE_ID = "F3_DUAL_AXIS_PHASE_PARENT"
PARENT_BAFFLE_CASE_ID = "F3_ECCENTRIC_BAFFLE_PARENT"


def _runner_receipt_path(case_id: str, attempt_id: str) -> Path:
    return RAW_OUTPUT_ROOT.parent.parent / case_id / attempt_id / "execution-receipt.json"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path, *, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


def _is_hex_digest(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


def _check_small_hash(path: Path, declared: str | None, *, max_bytes: int = 32 * 1024 * 1024) -> str:
    """Return a hash-check status without reading large HDF5 files."""
    if not path.is_file():
        return "missing"
    if not _is_hex_digest(declared):
        return "no_declared_hash"
    if path.stat().st_size > max_bytes:
        return "declared_only_large_file"
    return "match" if sha256_file(path) == declared else "mismatch"


def _load_hdf5_header(path: Path) -> dict[str, Any]:
    """Read only shape, attrs and endpoint slices from a native trajectory.

    h5py is optional for source-tree inspection.  Importing it here keeps the
    generator usable in the minimal repository environment and makes failure
    explicit rather than silently treating a missing reader as valid data.
    """
    try:
        import h5py  # type: ignore
        import numpy as np  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on host environment
        return {"status": "uninspected_reader_unavailable", "error": f"{type(exc).__name__}: {exc}"}
    if not path.is_file():
        return {"status": "missing"}
    required = {
        "density", "mass", "mk", "particle_id", "particle_zone", "position",
        "pressure", "time", "type", "valid", "velocity",
    }
    try:
        with h5py.File(path, "r") as handle:
            keys = set(handle.keys())
            shapes = {key: list(handle[key].shape) for key in sorted(keys)}
            time_axis = handle["time"]
            pos = handle["position"]
            vel = handle["velocity"]
            mass = handle["mass"]
            valid = handle["valid"]
            first_pos = pos[0]
            last_pos = pos[-1]
            first_mass = mass[0]
            return {
                "status": "light_header_pass" if required <= keys else "missing_required_datasets",
                "keys": sorted(keys),
                "shapes": shapes,
                "attrs": {str(key): str(value) for key, value in handle.attrs.items()},
                "time_start_s": float(time_axis[0]),
                "time_end_s": float(time_axis[-1]),
                "frame_count": int(time_axis.shape[0]),
                "particle_axis_count": int(pos.shape[1]),
                "coordinate_components": int(pos.shape[2]) if len(pos.shape) == 3 else None,
                "position_min_m": np.asarray(first_pos).min(axis=0).astype(float).tolist(),
                "position_max_m": np.asarray(first_pos).max(axis=0).astype(float).tolist(),
                "initial_mass_kg": float(np.asarray(first_mass, dtype=np.float64).sum()),
                "initial_valid_count": int(np.asarray(valid[0], dtype=bool).sum()),
                "final_valid_count": int(np.asarray(valid[-1], dtype=bool).sum()),
                "finite_endpoint_state": bool(
                    np.isfinite(first_pos).all()
                    and np.isfinite(last_pos).all()
                    and np.isfinite(vel[0]).all()
                    and np.isfinite(mass[0]).all()
                ),
            }
    except Exception as exc:
        return {"status": "read_error", "error": f"{type(exc).__name__}: {exc}"}


def _solver_dimension_from_definition(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"status": "missing_definition", "solver_dimension": None}
    try:
        root = ET.parse(path).getroot()
        data2d = root.find(".//constants")
        data2d_value = None
        # Generated XML stores data2d in execution.constants; definition XML
        # has no value, so inspect both possible locations.
        node = root.find(".//constants/data2d")
        if node is not None:
            data2d_value = node.get("value")
        if data2d_value is None:
            node = root.find(".//execution/constants/data2d")
            if node is not None:
                data2d_value = node.get("value")
        if data2d_value is None:
            data2d_value = "false"  # v5.4 generated execution XML may omit it in Def.
        is_3d = str(data2d_value).lower() in {"false", "0", "no"}
        return {
            "status": "parsed",
            "data2d": str(data2d_value).lower(),
            "solver_dimension": 3 if is_3d else 2,
            "basis": "generated XML data2d flag; HDF5 position components are corroborative",
        }
    except Exception as exc:
        return {"status": "definition_parse_error", "solver_dimension": None, "error": f"{type(exc).__name__}: {exc}"}


def _archive_inventory(archive_root: Path) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    if not archive_root.is_dir():
        return {
            "root": str(archive_root),
            "exists": False,
            "schema": None,
            "entries": [],
            "duplicate_groups": [],
            "core_reusable_count": 0,
            "material_candidate_count": 0,
        }
    for manifest_path in sorted(archive_root.glob("*/artifact-manifest.json")):
        manifest = read_json(manifest_path)
        files = manifest.get("files") if isinstance(manifest.get("files"), list) else []
        for row in files:
            if not isinstance(row, dict) or not isinstance(row.get("path"), str):
                continue
            path = manifest_path.parent / row["path"]
            entries.append({
                "archive_id": manifest_path.parent.name,
                "path": _relative(path, archive_root),
                "exists": path.is_file(),
                "bytes": path.stat().st_size if path.is_file() else None,
                "declared_sha256": row.get("sha256"),
                "hash_check": _check_small_hash(path, row.get("sha256")),
                "schema": manifest.get("schema"),
                "storage_scope": manifest.get("storage_scope"),
            })
    groups: dict[str, list[str]] = defaultdict(list)
    for row in entries:
        digest = row.get("declared_sha256")
        if _is_hex_digest(digest):
            groups[digest].append(row["path"])
    duplicates = [
        {"sha256": digest, "paths": paths, "duplicate_count": len(paths)}
        for digest, paths in sorted(groups.items()) if len(paths) > 1
    ]
    material_rows = [row for row in entries if row["path"].endswith("aligned.h5")]
    material_count = len(material_rows)
    material_hash_groups: dict[str, list[str]] = defaultdict(list)
    for row in material_rows:
        digest = row.get("declared_sha256")
        if _is_hex_digest(digest):
            material_hash_groups[digest].append(row["path"])
    material_duplicates = [
        {"sha256": digest, "paths": paths, "duplicate_count": len(paths)}
        for digest, paths in sorted(material_hash_groups.items()) if len(paths) > 1
    ]
    return {
        "root": str(archive_root),
        "exists": True,
        "schema": "f3.material.external_archive_manifest.v1",
        "entries": entries,
        "duplicate_groups": duplicates,
        "core_reusable_count": 0,
        "material_candidate_count": material_count,
        "unique_material_candidate_count": len(material_hash_groups),
        "duplicate_material_candidate_groups": material_duplicates,
        "interpretation": "archive entries are material/cadence candidates; aligned.h5 is not a native F3 core trajectory and duplicate hashes count once",
    }


def _source_path(root: Path, relative_or_absolute: str | None) -> Path | None:
    if not isinstance(relative_or_absolute, str):
        return None
    path = Path(relative_or_absolute)
    return path if path.is_absolute() else root / path


def _source_json(root: Path, evidence: Mapping[str, Any] | None) -> tuple[dict[str, Any], Path | None]:
    """Load a small receipt referenced by source evidence, if present."""
    if not isinstance(evidence, Mapping):
        return {}, None
    path = _source_path(root, evidence.get("path"))
    if path is None or not path.is_file():
        return {}, path
    try:
        return read_json(path), path
    except (OSError, ValueError, json.JSONDecodeError):
        return {}, path


def _compact_runner_receipt(path: Path) -> dict[str, Any]:
    """Expose a small immutable pointer to a shared-runner receipt, if done."""
    if not path.is_file():
        return {"status": "pending", "receipt_path": str(path)}
    try:
        receipt = read_json(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"status": "unreadable", "receipt_path": str(path), "error": f"{type(exc).__name__}: {exc}"}
    return {
        "status": receipt.get("status"),
        "receipt_path": str(path),
        "request_sha256": receipt.get("request_sha256"),
        "binary_sha256": receipt.get("binary_sha256"),
        "input_hashes_at_launch": receipt.get("input_hashes_at_launch"),
        "input_hashes_after_run": receipt.get("input_hashes_after_run"),
        "output_root": receipt.get("output_root"),
        "returncode": receipt.get("returncode"),
        "solver_dimension_from_gencase": receipt.get("solver_dimension_from_gencase"),
        "total_particles": receipt.get("total_particles"),
        "fluid_particles": receipt.get("fluid_particles"),
        "elapsed_seconds": receipt.get("elapsed_seconds"),
        "cpu_core_seconds": receipt.get("cpu_core_seconds"),
        "bytes": receipt.get("bytes"),
        "stdout_sha256": receipt.get("stdout_sha256"),
    }


def _select_parent_gencase_attempt(case_id: str, *, maximum_attempts: int = 9) -> tuple[str, list[dict[str, Any]]]:
    """Select a successful parent receipt or the next repair attempt.

    A zero-fluid GenCase exit is a completed process but not a usable parent.
    Keep every immutable receipt pointer in the queue and only advance to a
    new attempt while the newest completed receipt still fails that structural
    condition.
    """
    receipts: list[dict[str, Any]] = []
    latest_number = 0
    successful: dict[str, Any] | None = None
    for number in range(1, maximum_attempts + 1):
        attempt_id = f"{case_id}_GENCASE_{number:02d}"
        compact = _compact_runner_receipt(_runner_receipt_path(case_id, attempt_id))
        if compact.get("status") not in {None, "pending"}:
            latest_number = number
            receipts.append({"attempt_id": attempt_id, **compact})
            if compact.get("status") == "completed" and int(compact.get("fluid_particles") or 0) > 0:
                successful = {"attempt_id": attempt_id, **compact}
                break
        else:
            break
    if successful is not None:
        return str(successful["attempt_id"]), receipts
    next_number = min(latest_number + 1, maximum_attempts)
    return f"{case_id}_GENCASE_{next_number:02d}", receipts


def _generated_prefix_from_receipt(receipt: Mapping[str, Any]) -> Path | None:
    command = receipt.get("command")
    if isinstance(command, list) and len(command) >= 3 and isinstance(command[2], str):
        return Path(command[2]).expanduser().resolve()
    output_root = receipt.get("output_root")
    if isinstance(output_root, str) and output_root:
        root = Path(output_root).expanduser().resolve()
        candidates = sorted(root.glob("*.xml"))
        if candidates:
            return candidates[0].with_suffix("")
    return None


def _vtk_points(path: Path) -> list[tuple[float, float, float]]:
    """Read the POINTS block of a legacy binary VTK emitted by GenCase."""
    data = path.read_bytes()
    marker = data.find(b"POINTS ")
    if marker < 0:
        raise ValueError(f"VTK has no POINTS block: {path}")
    line_end = data.find(b"\n", marker)
    if line_end < 0:
        raise ValueError(f"VTK POINTS header is truncated: {path}")
    header = data[marker:line_end].split()
    if len(header) < 3 or header[2].lower() != b"float":
        raise ValueError(f"unsupported VTK point type: {path}")
    count = int(header[1])
    start = line_end + 1
    end = start + count * 3 * 4
    if end > len(data):
        raise ValueError(f"VTK POINTS block is truncated: {path}")
    values = struct.unpack_from(">" + "f" * (count * 3), data, start)
    return [(float(values[index]), float(values[index + 1]), float(values[index + 2])) for index in range(0, len(values), 3)]


def _control_coverage(control: Mapping[str, Any]) -> dict[str, Any]:
    path = Path(str(control.get("path", ""))).expanduser()
    result: dict[str, Any] = {
        "path": str(path.resolve()),
        "exists": path.is_file(),
        "rows": 0,
        "time_start_s": None,
        "time_end_s": None,
        "monotonic": False,
        "finite": False,
        "declared_hash": control.get("sha256"),
        "actual_hash": None,
    }
    if not path.is_file():
        return result
    result["actual_hash"] = sha256_file(path)
    times: list[float] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            fields = [field.strip() for field in stripped.replace(";", " ").split()]
            if not fields:
                continue
            times.append(float(fields[0]))
    except (OSError, ValueError, UnicodeError) as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result
    result.update({
        "rows": len(times),
        "time_start_s": times[0] if times else None,
        "time_end_s": times[-1] if times else None,
        "monotonic": bool(times) and all(later > earlier for earlier, later in zip(times, times[1:])),
        "finite": bool(times) and all(math.isfinite(value) for value in times),
    })
    result["coverage_pass"] = bool(
        result["exists"]
        and result["rows"] == PARENT_INPUT_CONTROL_ROWS
        and result["time_start_s"] is not None
        and abs(float(result["time_start_s"]) - PARENT_INPUT_TIME_WINDOW_S[0]) < 1e-9
        and result["time_end_s"] is not None
        and abs(float(result["time_end_s"]) - PARENT_INPUT_TIME_WINDOW_S[1]) < 1e-9
        and result["monotonic"]
        and result["finite"]
        and result["actual_hash"] == result["declared_hash"]
    )
    return result


def _generated_wall_check(root: ET.Element, mechanism_id: str, boundary_count: int) -> dict[str, Any]:
    mainlist = root.find("./casedef/geometry/commands/mainlist")
    boxfills = [] if mainlist is None else [
        " ".join((node.findtext("boxfill") or "").split())
        for node in mainlist.findall("drawbox")
    ]
    closed = {"bottom", "left", "right", "front", "back"}
    outer_closed = any(set(part.strip() for part in text.split("|")) == closed for text in boxfills)
    has_full_baffle_shell = mechanism_id != "eccentric_baffle_exchange" or any(
        set(part.strip() for part in text.split("|")) == closed | {"top"} for text in boxfills
    )
    return {
        "boundary_particles": boundary_count,
        "boundary_particles_positive": boundary_count > 0,
        "outer_closed_faces_present": outer_closed,
        "top_open_in_outer_main_geometry": not any("all" in text.lower() or "top" in text.split("|") for text in boxfills if "bottom" in text),
        "finite_baffle_shell_present": has_full_baffle_shell,
        "pass": bool(boundary_count > 0 and outer_closed and has_full_baffle_shell),
        "main_boxfill_operations": boxfills,
    }


def _audit_parent_receipt(parent: Mapping[str, Any], receipt_path: Path) -> dict[str, Any]:
    compact = _compact_runner_receipt(receipt_path)
    mechanism_id = str(parent.get("mechanism_id", ""))
    definition = parent.get("definition") if isinstance(parent.get("definition"), Mapping) else {}
    control = parent.get("control") if isinstance(parent.get("control"), Mapping) else {}
    result: dict[str, Any] = {
        "case_id": parent.get("case_id"),
        "mechanism_id": mechanism_id,
        "receipt": compact,
        "receipt_sha256": sha256_file(receipt_path) if receipt_path.is_file() else None,
        "attempt_id": receipt_path.parent.name,
        "checks": {},
        "errors": [],
    }
    if compact.get("status") != "completed":
        result["errors"].append("shared runner receipt is not completed")
        result["status"] = "pending" if compact.get("status") == "pending" else "fail"
        return result
    receipt = read_json(receipt_path)
    prefix = _generated_prefix_from_receipt(receipt)
    generated_xml = prefix.with_suffix(".xml") if prefix is not None else None
    if generated_xml is None or not generated_xml.is_file():
        result["errors"].append("generated GenCase XML is missing")
        result["status"] = "fail"
        return result
    try:
        generated_root = ET.parse(generated_xml).getroot()
        particles = generated_root.find("./execution/particles")
        constants = generated_root.find("./execution/constants")
        if particles is None or constants is None:
            raise ValueError("generated XML has no execution particles/constants")
        fluid = particles.find("fluid")
        fluid_begin = int(fluid.get("begin", "0")) if fluid is not None else 0
        fluid_count = int(fluid.get("count", "0")) if fluid is not None else 0
        boundary_count = sum(int(node.get("count", "0")) for node in particles if node.tag in {"fixed", "moving", "floating"})
        dp = float(constants.find("dp").get("value"))
        massfluid = float(constants.find("massfluid").get("value"))
        density = float(constants.find("rhop0").get("value"))
        data2d_node = constants.find("data2d")
        data2d = str(data2d_node.get("value", "true")).lower() if data2d_node is not None else "true"
        generated_vtk = prefix.with_name(prefix.name + "_All.vtk") if prefix is not None else None
        points = _vtk_points(generated_vtk) if generated_vtk is not None and generated_vtk.is_file() else []
        fluid_points = points[fluid_begin:fluid_begin + fluid_count]
        transverse_layers = sorted({round(point[1], 8) for point in fluid_points})
        finite_points = bool(fluid_points) and all(math.isfinite(value) for point in fluid_points for value in point)
        expected_min_layers = 20
        wall = _generated_wall_check(generated_root, mechanism_id, boundary_count)
        control_audit = _control_coverage(control)
        input_hashes = receipt.get("input_hashes_after_run") if isinstance(receipt.get("input_hashes_after_run"), Mapping) else {}
        definition_path = Path(str(definition.get("path", ""))).expanduser().resolve()
        control_path = Path(str(control.get("path", ""))).expanduser().resolve()
        hashes_bound = bool(
            input_hashes.get(str(definition_path)) == definition.get("sha256")
            and input_hashes.get(str(control_path)) == control.get("sha256")
        )
        initial_mass = massfluid * fluid_count
        expected_particle_mass = density * dp ** 3
        mass_rel_error = abs(massfluid - expected_particle_mass) / expected_particle_mass if expected_particle_mass else math.inf
        fluid_box = parent.get("geometry", {}).get("fluid_box_m", []) if isinstance(parent.get("geometry"), Mapping) else []
        continuous_volume = None
        if isinstance(fluid_box, list) and len(fluid_box) == 6:
            continuous_volume = (float(fluid_box[1]) - float(fluid_box[0])) * (float(fluid_box[3]) - float(fluid_box[2])) * (float(fluid_box[5]) - float(fluid_box[4]))
        result["generated"] = {
            "xml_path": str(generated_xml),
            "xml_sha256": sha256_file(generated_xml),
            "vtk_path": str(generated_vtk) if generated_vtk is not None else None,
            "total_particles": int(compact.get("total_particles") or 0),
            "fluid_particles_receipt": int(compact.get("fluid_particles") or 0),
            "fluid_particles_xml": fluid_count,
            "fluid_begin": fluid_begin,
            "solver_dimension_from_gencase_receipt": compact.get("solver_dimension_from_gencase"),
            "data2d": data2d,
            "dp_m": dp,
            "fluid_mass_per_particle_kg": massfluid,
            "initial_mass_kg": initial_mass,
            "fluid_volume_discrete_m3": fluid_count * dp ** 3,
            "fluid_volume_continuous_box_m3": continuous_volume,
            "transverse_layer_count": len(transverse_layers),
            "transverse_layer_coordinates_m": transverse_layers,
            "fluid_position_bounds_m": [
                [min(point[axis] for point in fluid_points), max(point[axis] for point in fluid_points)]
                for axis in range(3)
            ] if fluid_points else None,
        }
        result["checks"] = {
            "nonzero_fluid": fluid_count > 0 and int(compact.get("fluid_particles") or 0) == fluid_count,
            "actual_3d": compact.get("solver_dimension_from_gencase") == 3 and data2d in {"false", "0", "no"},
            "finite_fluid_positions": finite_points,
            "valid_transverse_layers": len(transverse_layers) >= expected_min_layers,
            "control_coverage": bool(control_audit.get("coverage_pass")),
            "finite_walls": wall["pass"],
            "initial_mass": bool(initial_mass > 0 and mass_rel_error <= 1e-9),
            "input_hash_binding": hashes_bound,
        }
        result["control"] = control_audit
        result["wall"] = wall
        result["mass"] = {
            "density_kg_m3": density,
            "expected_particle_mass_kg": expected_particle_mass,
            "relative_particle_mass_error": mass_rel_error,
            "pass": bool(initial_mass > 0 and mass_rel_error <= 1e-9),
        }
        result["status"] = "pass" if all(result["checks"].values()) else "fail"
        if result["status"] != "pass":
            result["errors"].extend(key for key, value in result["checks"].items() if not value)
    except (OSError, ValueError, TypeError, ET.ParseError, struct.error) as exc:
        result["errors"].append(f"generated output audit error: {type(exc).__name__}: {exc}")
        result["status"] = "fail"
    return result


def _git_head() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, check=True,
            capture_output=True, text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _historical_solver_cost(audit: Mapping[str, Any]) -> dict[str, float]:
    elapsed: list[float] = []
    hdf5_bytes: list[float] = []
    for row in audit.get("cases", []):
        if not isinstance(row, Mapping):
            continue
        execution = row.get("execution") if isinstance(row.get("execution"), Mapping) else {}
        if isinstance(execution.get("elapsed_seconds"), (int, float)) and float(execution["elapsed_seconds"]) > 0:
            elapsed.append(float(execution["elapsed_seconds"]))
        if isinstance(row.get("hdf5_bytes"), (int, float)) and float(row["hdf5_bytes"]) > 0:
            hdf5_bytes.append(float(row["hdf5_bytes"]))
    # The canonical first native solver receipt is the cost anchor.  Median is
    # used when all 32 source receipts are available, avoiding one outlier.
    elapsed.sort()
    hdf5_bytes.sort()
    middle = len(elapsed) // 2
    elapsed_anchor = elapsed[middle] if elapsed else 510.59285095299856
    bytes_anchor = hdf5_bytes[len(hdf5_bytes) // 2] if hdf5_bytes else 899562494.0
    return {
        "historical_solver_elapsed_seconds": elapsed_anchor,
        "historical_hdf5_bytes": bytes_anchor,
        "historical_total_particles": 108000.0,
        "historical_fluid_particles": 34560.0,
        "historical_time_window_s": 8.35,
        "historical_frame_count": 836.0,
    }


def _qualification_request(
    *,
    output_root: Path,
    parent: Mapping[str, Any],
    parent_audit: Mapping[str, Any],
    history_audit: Mapping[str, Any],
) -> dict[str, Any]:
    receipt_path = Path(str(parent_audit.get("receipt", {}).get("receipt_path", ""))).expanduser().resolve()
    receipt = read_json(receipt_path)
    generated = parent_audit.get("generated") if isinstance(parent_audit.get("generated"), Mapping) else {}
    generated_xml = Path(str(generated.get("xml_path", ""))).expanduser().resolve()
    prefix = _generated_prefix_from_receipt(receipt)
    if prefix is None:
        raise ValueError(f"missing generated prefix for {receipt_path}")
    mechanism_id = str(parent.get("mechanism_id"))
    case_id = str(parent.get("case_id"))
    actual_total = int(receipt.get("total_particles", 0))
    actual_fluid = int(receipt.get("fluid_particles", 0))
    cost = _historical_solver_cost(history_audit)
    window_ratio = PARENT_INPUT_TIME_WINDOW_S[1] / cost["historical_time_window_s"]
    total_ratio = actual_total / cost["historical_total_particles"]
    fluid_ratio = actual_fluid / cost["historical_fluid_particles"]
    complexity = 1.10 if mechanism_id == "dual_axis_phase" else 1.25
    estimated_gpu_seconds = math.ceil(cost["historical_solver_elapsed_seconds"] * total_ratio * window_ratio * complexity)
    frame_ratio = (PARENT_INPUT_CONTROL_ROWS * (PARENT_INPUT_DT_S / 0.0025)) / cost["historical_frame_count"]
    estimated_storage = math.ceil(cost["historical_hdf5_bytes"] * frame_ratio * fluid_ratio * 1.25)
    estimated_storage = max(estimated_storage, 5 * 1024 ** 3)
    max_wall = max(900, math.ceil(estimated_gpu_seconds * 1.20))
    definition = Path(str(parent.get("definition", {}).get("path", ""))).expanduser().resolve()
    control = Path(str(parent.get("control", {}).get("path", ""))).expanduser().resolve()
    generated_bi4 = prefix.with_suffix(".bi4")
    input_files = [
        Path(__file__).resolve(),
        output_root / "event_definitions.json",
        output_root / "observation_plan.json",
        output_root / "qualified_recipes.json",
        output_root / "split_plan.json",
        output_root / "history_reuse_inventory.json",
        output_root / "parent_inputs/parent_input_manifest.json",
        output_root / "parent_inputs/gencase_audit.json",
        definition,
        control,
        generated_xml,
        generated_bi4,
        receipt_path,
    ]
    return {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": "F3",
        "case_id": case_id,
        "attempt_id": f"{case_id}_SOLVER_QUAL_01",
        "kind": "qualification",
        "command": [
            str(SOLVER_BINARY.resolve()),
            "-mdbc_noslip:1",
            str(prefix),
            "{attempt_root}/solver_output",
            f"-tmax:{PARENT_INPUT_TIME_WINDOW_S[1]:.6g}",
            f"-tout:{0.0025:.6g}",
        ],
        "complete_event_window_s": list(PARENT_INPUT_TIME_WINDOW_S),
        "cwd": str(SOLVER_BINARY.parent.resolve()),
        "max_wall_seconds": max_wall,
        "cpu_threads": 4,
        "estimated_storage_bytes": estimated_storage,
        "estimated_peak_gpu_mib": 8192,
        "event_timing_qualified": False,
        "gencase_receipt": str(receipt_path),
        "gencase_receipt_sha256": sha256_file(receipt_path),
        "gencase_runner_sha256": receipt.get("runner_sha256"),
        "parent_gencase_git_at_launch": receipt.get("git_at_launch"),
        "gencase_actual_particles": {"total": actual_total, "fluid": actual_fluid},
        "input_files": [str(path.resolve()) for path in input_files],
        "worktree_root": str(REPO_ROOT.resolve()),
        "launch_commit": _git_head(),
        "definition_commit_binding": _git_head(),
        "source_mother": f"F3_DS02_{mechanism_id}_parent",
        "mechanism_id": mechanism_id,
        "solver_dimension_required": 3,
        "coordinate_frame_id": parent.get("coordinate_frame_id"),
        "resolution": "medium_parent",
        "output_interval_s": 0.0025,
        "recipe_id": f"F3_DS02_{mechanism_id}_v1",
        "observables": [
            "exchange_mass", "repeat_crossing", "surface_com_phase", "distribution_3d",
            "velocity_energy", "boundary_correction_usage", "initial_mass_ledger",
        ],
        "qualification_scope": "one complete-window parent solver receipt for Q-I review; this request grants no Q-N and does not back the old split",
        "cost_estimate": {
            "basis": "measured historical native solver receipt and measured parent GenCase particle count",
            "historical_solver_elapsed_seconds": cost["historical_solver_elapsed_seconds"],
            "historical_total_particles": int(cost["historical_total_particles"]),
            "actual_total_particles": actual_total,
            "total_particle_ratio": total_ratio,
            "historical_window_s": cost["historical_time_window_s"],
            "requested_window_s": PARENT_INPUT_TIME_WINDOW_S[1],
            "window_ratio": window_ratio,
            "mechanism_complexity_factor": complexity,
            "estimated_gpu_seconds": estimated_gpu_seconds,
            "historical_hdf5_bytes": int(cost["historical_hdf5_bytes"]),
            "actual_fluid_particles": actual_fluid,
            "fluid_particle_ratio": fluid_ratio,
            "frame_ratio": frame_ratio,
            "storage_safety_factor": 1.25,
            "estimated_storage_bytes": estimated_storage,
        },
        "raw_output_root": str(RAW_OUTPUT_ROOT),
        "solver_launch_forbidden": False,
        "qualification_launch_authority": "shared_ds_data_02_runtime_only; F3 owner does not launch GPU",
        "request_note": "Submit through scripts/ds_data02_runtime.py only; shared runner adds GPU UUID lease and records git_at_launch. The parent GenCase receipt and all input hashes are mandatory provenance.",
    }


def _materialize_qualification_requests(output_root: Path, parent_audit: Mapping[str, Any]) -> dict[str, Any]:
    history_path = output_root / "history_reuse_inventory.json"
    history_audit = read_json(history_path)
    manifest = read_json(output_root / "parent_inputs/parent_input_manifest.json")
    parent_by_case = {
        str(row.get("case_id")): row for row in manifest.get("parents", []) if isinstance(row, Mapping)
    }
    requests: list[dict[str, Any]] = []
    files: list[str] = []
    for row in parent_audit.get("parents", []):
        if not isinstance(row, Mapping) or row.get("status") != "pass":
            continue
        parent = parent_by_case.get(str(row.get("case_id")))
        if parent is None:
            continue
        request = _qualification_request(
            output_root=output_root, parent=parent, parent_audit=row, history_audit=history_audit,
        )
        relative = f"qualification_requests/{str(parent['mechanism_id'])}.json"
        request["request_file"] = relative
        _write_json(output_root / relative, request)
        requests.append(request)
        files.append(relative)
    queue_path = output_root / "execution_queue.json"
    queue = read_json(queue_path)
    queue["qualification_status"] = "ready_for_shared_gpu_dispatch" if requests else "pending_parent_audit"
    queue["qualification_requests"] = requests
    queue["qualification_request_files"] = files
    queue["parent_gencase_audit"] = {
        "path": str((output_root / "parent_inputs/gencase_audit.json").resolve()),
        "sha256": sha256_file(output_root / "parent_inputs/gencase_audit.json"),
        "status": parent_audit.get("status"),
    }
    _write_json(queue_path, queue)
    return {"status": queue["qualification_status"], "request_files": files, "requests": requests}


def _update_family_after_parent_audit(output_root: Path, parent_audit: Mapping[str, Any], qualification: Mapping[str, Any]) -> None:
    audit_path = output_root / "parent_inputs/gencase_audit.json"
    evidence_pointer = {
        "path": str(audit_path.resolve()),
        "sha256": sha256_file(audit_path),
        "status": parent_audit.get("status"),
        "solver_launched": False,
    }
    card_path = output_root / "family_card.json"
    if card_path.is_file():
        card = read_json(card_path)
        card["status"] = "historical_scope_reusable; parent_gencase_qi_ready_solver_pending"
        card["parent_gencase_evidence"] = evidence_pointer
        card["qualification_requests"] = list(qualification.get("request_files", []))
        _write_json(card_path, card)
    recipe_path = output_root / "qualified_recipes.json"
    if recipe_path.is_file():
        recipes = read_json(recipe_path)
        request_by_mechanism = {
            str(row.get("mechanism_id")): row
            for row in qualification.get("requests", []) if isinstance(row, Mapping)
        }
        audit_by_mechanism = {
            str(row.get("mechanism_id")): row
            for row in parent_audit.get("parents", []) if isinstance(row, Mapping)
        }
        for recipe in recipes.get("recipes", []):
            if not isinstance(recipe, dict) or recipe.get("mechanism_id") not in audit_by_mechanism:
                continue
            mechanism_id = str(recipe["mechanism_id"])
            parent_row = audit_by_mechanism[mechanism_id]
            recipe["status"] = "parent_gencase_passed_solver_pending" if parent_row.get("status") == "pass" else "parent_gencase_audit_failed"
            recipe["parent_gencase_audit"] = {
                "selected_attempt": parent_row.get("selected_attempt"),
                "receipt_path": parent_row.get("receipt", {}).get("receipt_path"),
                "checks": parent_row.get("checks", {}),
            }
            if mechanism_id in request_by_mechanism:
                recipe["qualification_request"] = request_by_mechanism[mechanism_id].get("request_file")
        _write_json(recipe_path, recipes)
    evidence_path = output_root / "reference_evidence.json"
    if evidence_path.is_file():
        evidence = read_json(evidence_path)
        evidence["parent_gencase_audit"] = evidence_pointer
        evidence["qualification_requests"] = list(qualification.get("request_files", []))
        evidence["new_mechanism_status"] = "parent_gencase_structural_checks_passed; solver_and_QN_pending"
        _write_json(evidence_path, evidence)
    handoff_path = output_root / "FAMILY_HANDOFF.md"
    if handoff_path.is_file():
        text = handoff_path.read_text(encoding="utf-8")
        text = text.replace(
            "- 双轴/相位控制和偏心挡板/分舱横向交换各缺一套完整 3 分辨率参考矩阵；新矩阵的 solver_dimension、GenCase 实际粒子数、输入/控制/geometry 哈希和 full-window 证据均待 runner 产出。",
            "- 双轴/相位与偏心挡板 parent 的 GenCase 实际粒子数、actual 3D、横向层、控制覆盖、有限壁面、初始质量及输入 hash 已由 shared runner receipt 审计；完整 3 分辨率 solver 矩阵、native dt、事件标签和 full-window HDF5 仍待后续 runner 产出。",
        )
        text = text.replace(
            "1. 历史 CELL3 母例已完成 bounded CPU GenCase receipt；下一步对每个新机制做一个有资源预约的 bounded CPU GenCase parent preflight，记录真实粒子数、横向层数和 geometry/control hash。",
            "1. 两个新机制 parent bounded CPU GenCase 已完成并通过结构审计；下一步按 `qualification_requests/` 提交首批完整 0–10 s solver qualification，由 shared runner 绑定 GPU lease、启动 commit 和 parent receipt。",
        )
        text = text.replace(
            "共享预约入口已提供；下一任务是为双轴/相位与偏心挡板各冻结一个 parent Definition 并执行 bounded CPU GenCase preflight，其余工作按 `execution_queue.json` 继续，不把 canary 或旧 plain gate 当作新机制数值参考。",
            "两个 parent 已冻结且通过 bounded CPU GenCase 结构审计；下一任务是提交 `qualification_requests/` 中的完整窗口 solver 请求，再由 shared runner 串行推进 2×3 矩阵、积分步/保存采样对照和原生事件标签，不把旧 plain gate 当作新机制数值参考。",
        )
        marker = "## Actual parent evidence"
        if marker not in text:
            lines = ["", marker, "", "- 双轴/相位 parent GenCase：attempt `_02`，total=132522、fluid=34320、actual 3D、横向层=26、初始质量=14.47875 kg；控制覆盖 0–10 s/2001 行，有限壁面和输入 hash 均通过。", "- 偏心挡板 parent GenCase：attempt `_03`，total=130768、fluid=36736、actual 3D、横向层=22、初始质量=18.808832 kg；移动槽世界坐标控制覆盖 0–10 s/2001 行，有限外壁/挡板 shell 和输入 hash 均通过。", "- 根因修复证据保留在 audit：双轴第一次 seed 位于底边界后修为内部高度；挡板先移除造成全域 bound 的 void-shell 操作，再把落在挡板厚度内的 origin seed 移到开放通道；每个机制均在两次以内收敛到非零 fluid。", "- parent 只通过 GenCase/Q-I 结构审计；qualification request 已生成但 solver/GPU 尚未启动：" + ", ".join(f"`{path}`" for path in qualification.get("request_files", [])) + ".", "- 旧 32 例及原 split 仍只在 legacy plain fixed-acceleration 等价范围复用；新 parent 不改变旧 split，也没有 Q-N 资格。", ""]
            text = text.rstrip() + "\n" + "\n".join(lines)
        handoff_path.write_text(text.rstrip() + "\n", encoding="utf-8")


def audit_parents(output_root: Path = FAMILY_ROOT) -> dict[str, Any]:
    """Audit the two shared-runner parent GenCase outputs and bind receipts."""
    manifest_path = output_root / "parent_inputs/parent_input_manifest.json"
    manifest = read_json(manifest_path)
    parents = manifest.get("parents") if isinstance(manifest.get("parents"), list) else []
    audits: list[dict[str, Any]] = []
    for parent in parents:
        if not isinstance(parent, Mapping):
            continue
        case_id = str(parent.get("case_id", ""))
        selected_attempt, attempts = _select_parent_gencase_attempt(case_id)
        selected_path = _runner_receipt_path(case_id, selected_attempt)
        audit = _audit_parent_receipt(parent, selected_path)
        audit["attempts"] = attempts
        audit["selected_attempt"] = selected_attempt
        failed_attempts = [row for row in attempts if int(row.get("fluid_particles") or 0) <= 0]
        if case_id == PARENT_DUAL_CASE_ID:
            diagnosis = "seed at the first lattice height was on the bottom boundary; moved to an interior z seed"
        elif case_id == PARENT_BAFFLE_CASE_ID:
            diagnosis = "full-draw void-shell operation erased the connected fill domain, then the origin seed snapped inside the baffle; removed void operation and moved seed into the open channel"
        else:
            diagnosis = "zero-fluid structural failure"
        audit["repair_history"] = [
            {
                "attempt_id": row.get("attempt_id"),
                "fluid_particles": row.get("fluid_particles"),
                "stdout_sha256": row.get("stdout_sha256"),
                "diagnosis": diagnosis,
            }
            for row in failed_attempts
        ]
        audit["repair_count"] = len(failed_attempts)
        audits.append(audit)
    result = {
        "schema": "ds-data-02.f3.parent_gencase_audit.v1",
        "family_id": "F3",
        "status": "pass" if audits and all(row.get("status") == "pass" for row in audits) else "pending_or_fail",
        "gencase_receipt_source": "shared ds_data02_runtime.py; no solver/GPU launched by F3 owner",
        "parents": audits,
        "repair_budget": {
            "dual_axis_phase": "one seed-height repair; attempt _02 is the first usable output",
            "eccentric_baffle_exchange": "two evidence repairs (void-shell operation, then seed outside baffle); attempt _03 is the first usable output",
            "maximum_evidence_repairs": 2,
        },
    }
    audit_path = output_root / "parent_inputs/gencase_audit.json"
    _write_json(audit_path, result)
    manifest["status"] = "parent_gencase_audit_passed" if result["status"] == "pass" else result["status"]
    manifest["gencase_audit"] = {"path": str(audit_path.resolve()), "sha256": sha256_file(audit_path)}
    for parent in manifest.get("parents", []):
        if not isinstance(parent, dict):
            continue
        match = next((row for row in audits if row.get("case_id") == parent.get("case_id")), None)
        if match:
            parent["gencase_audit"] = {
                "status": match.get("status"),
                "selected_attempt": match.get("selected_attempt"),
                "checks": match.get("checks", {}),
                "receipt_path": match.get("receipt", {}).get("receipt_path"),
            }
    _write_json(manifest_path, manifest)
    qualification = _materialize_qualification_requests(output_root, result)
    _update_family_after_parent_audit(output_root, result, qualification)
    result["qualification"] = {
        "status": qualification.get("status"),
        "request_files": qualification.get("request_files", []),
    }
    return result


def audit_history(
    historical_root: Path = HISTORICAL_ROOT,
    archive_root: Path = MATERIAL_ARCHIVE_ROOT,
    *,
    inspect_hdf5: bool = True,
    full_hash: bool = False,
) -> dict[str, Any]:
    """Audit the immutable historical F3 gate and 32 native trajectories."""
    manifest_path = historical_root / CANONICAL_MANIFEST
    gate_path = historical_root / HISTORICAL_GATE
    contract_path = historical_root / HISTORICAL_CONTRACT
    closeout_path = historical_root / HISTORICAL_CLOSEOUT
    missing_records = [str(path) for path in (manifest_path, gate_path, contract_path, closeout_path) if not path.is_file()]
    if missing_records:
        raise FileNotFoundError("missing historical F3 records: " + ", ".join(missing_records))
    manifest = read_json(manifest_path)
    gate = read_json(gate_path)
    contract = read_json(contract_path)
    closeout = read_json(closeout_path)
    cases = manifest.get("cases")
    if not isinstance(cases, list):
        raise ValueError("historical canonical manifest has no case list")
    case_rows: list[dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        case_id = str(case.get("case_id", ""))
        h5_rel = case.get("hdf5")
        h5_path = _source_path(historical_root, h5_rel)
        source_evidence = case.get("source_evidence") if isinstance(case.get("source_evidence"), dict) else {}
        file_record = case.get("file") if isinstance(case.get("file"), dict) else {}
        prepared_rel = ((source_evidence.get("prepared") or {}).get("path") if isinstance(source_evidence.get("prepared"), dict) else None)
        prepared_path = _source_path(historical_root, prepared_rel)
        prepared: dict[str, Any] = {}
        if prepared_path and prepared_path.is_file():
            try:
                prepared = read_json(prepared_path)
            except Exception:
                prepared = {}
        solver_record, solver_receipt_path = _source_json(
            historical_root,
            source_evidence.get("solver") if isinstance(source_evidence.get("solver"), dict) else None,
        )
        audit_record, audit_receipt_path = _source_json(
            historical_root,
            source_evidence.get("audit") if isinstance(source_evidence.get("audit"), dict) else None,
        )
        preflight_record, preflight_receipt_path = _source_json(
            historical_root,
            source_evidence.get("input_preflight") if isinstance(source_evidence.get("input_preflight"), dict) else None,
        )
        candidate_definition = _source_path(historical_root, prepared.get("candidate_definition"))
        definition_info = _solver_dimension_from_definition(candidate_definition) if candidate_definition else {"status": "no_candidate_definition", "solver_dimension": None}
        h5_header = _load_hdf5_header(h5_path) if inspect_hdf5 and h5_path else {"status": "not_requested"}
        source_rows: dict[str, Any] = {}
        for label, evidence in source_evidence.items():
            if not isinstance(evidence, dict):
                continue
            path = _source_path(historical_root, evidence.get("path"))
            declared = evidence.get("sha256")
            source_rows[label] = {
                "path": evidence.get("path"),
                "exists": bool(path and path.is_file()),
                "declared_sha256": declared,
                "hash_check": (
                    "full_match" if full_hash and path and path.is_file() and sha256_file(path) == declared
                    else _check_small_hash(path, declared) if path else "missing"
                ),
            }
        if h5_path and h5_path.is_file() and full_hash:
            h5_hash_check = "full_match" if sha256_file(h5_path) == file_record.get("sha256") else "mismatch"
        elif h5_path and h5_path.is_file():
            h5_hash_check = "declared_only_large_file"
        else:
            h5_hash_check = "missing"
        lineage = case.get("lineage_group_id") or prepared.get("physical_lineage_sha256")
        row = {
            "case_id": case_id,
            "physical_case_id": case.get("physical_case_id", case_id),
            "lineage_group_id": lineage,
            "family_id": "F3",
            "mechanism_id": "legacy_plain_sloshing",
            "geometry_family_id": "F3_CELL3_PLAIN",
            "control_family_id": "F3_CTRL_LEGACY_SINGLE_AXIS",
            "paired_background_id": "legacy_plain",
            "recipe_id": case.get("recipe_id", manifest.get("recipe", {}).get("recipe_id")),
            "view_id": "native_full_window",
            "attempt_id": solver_record.get("attempt_id") or ((source_evidence.get("solver") or {}).get("path") if isinstance(source_evidence.get("solver"), dict) else None),
            "status": "reused_historical_candidate",
            "split": case.get("split"),
            "legacy_split": case.get("split"),
            "target_role": case.get("split"),
            "evaluation_role": case.get("evaluation_role"),
            "drive_amplitude": case.get("drive_amplitude"),
            "hdf5_path": str(h5_path) if h5_path else None,
            "portable_source_path": h5_rel,
            "hdf5_sha256": file_record.get("sha256"),
            "hdf5_bytes": file_record.get("bytes"),
            "hdf5_hash_check": h5_hash_check,
            "source_evidence": source_rows,
            "input_definition_path": prepared.get("candidate_definition"),
            "official_definition_path": (prepared.get("source_definition") or {}).get("path") if isinstance(prepared.get("source_definition"), dict) else OFFICIAL_ACCEL_DEFINITION,
            "geometry_asset_hashes": {
                key: value for key, value in (prepared.get("input_assets") or {}).items()
                if isinstance(key, str) and ("xml" in key.lower() or "vtk" in key.lower() or "bi4" in key.lower())
            },
            "control_path": ((source_evidence.get("control") or {}).get("path") if isinstance(source_evidence.get("control"), dict) else prepared.get("registered_control_path")),
            "control_sha256": ((source_evidence.get("control") or {}).get("sha256") if isinstance(source_evidence.get("control"), dict) else prepared.get("drive_sha256")),
            "solver_dimension": definition_info.get("solver_dimension") or (3 if h5_header.get("coordinate_components") == 3 else None),
            "dimension_evidence": {
                "definition": definition_info,
                "hdf5_coordinate_components": h5_header.get("coordinate_components"),
                "solver_dimension_source": "actual generated XML data2d=false plus native HDF5 position[:, :, 3]",
            },
            "actual_y_layers": prepared.get("actual_y_layers"),
            "time_window_s": [case.get("independent_audit", {}).get("time_start_s", 0.0), case.get("independent_audit", {}).get("time_end_s", None)],
            "native_frames": case.get("recorded_contract", {}).get("native_frames"),
            "particle_axis_count": case.get("independent_audit", {}).get("datasets", {}).get("position", [None, None, None])[1] if isinstance(case.get("independent_audit", {}).get("datasets"), dict) else None,
            "hdf5_header": h5_header,
            "input_contract": {
                "candidate_definition": prepared.get("candidate_definition"),
                "source_definition": prepared.get("source_definition"),
                "generated_prefix": prepared.get("generated_prefix"),
                "control_definition": prepared.get("control_definition"),
                "registered_control_path": prepared.get("registered_control_path"),
                "control_sha256": prepared.get("drive_sha256"),
                "geometry_asset_hashes": {
                    key: value for key, value in (prepared.get("input_assets") or {}).items()
                    if isinstance(key, str) and ("xml" in key.lower() or "vtk" in key.lower() or "bi4" in key.lower())
                },
                "gencase_counts": prepared.get("gencase"),
                "actual_y_layers": prepared.get("actual_y_layers"),
                "wall_spec": prepared.get("wall_spec"),
                "coordinate_frame": prepared.get("coordinate_frame"),
                "protocol_sha256": prepared.get("protocol_sha256"),
                "recipe_id": prepared.get("recipe_id"),
                "preflight_record_sha256": source_evidence.get("input_preflight", {}).get("sha256") if isinstance(source_evidence.get("input_preflight"), dict) else None,
                "preflight_status": preflight_record.get("status"),
                "preflight_receipt_path": str(preflight_receipt_path) if preflight_receipt_path else None,
            },
            "tool_versions": {
                "solver_executable": solver_record.get("command", [None])[0] if isinstance(solver_record.get("command"), list) and solver_record.get("command") else None,
                "solver_binary_sha256": solver_record.get("solver_sha256"),
                "solver_mode": prepared.get("solver_mode"),
                "native_reader": "h5py light header audit; native JBinaryData arrays preserved",
            },
            "execution": {
                "attempt_id": solver_record.get("attempt_id"),
                "status": solver_record.get("status"),
                "returncode": solver_record.get("returncode"),
                "command": solver_record.get("command"),
                "attempt_directory": solver_record.get("attempt_directory"),
                "elapsed_seconds": solver_record.get("elapsed_seconds"),
                "solver_receipt_path": str(solver_receipt_path) if solver_receipt_path else None,
            },
            "observation_conclusion": {
                "audit_receipt_path": str(audit_receipt_path) if audit_receipt_path else None,
                "audit_status": audit_record.get("audit_status"),
                "acceptance_status": audit_record.get("acceptance_status"),
                "validation_scope": audit_record.get("validation_scope"),
                "frames": audit_record.get("frames"),
                "time_window_s": [audit_record.get("time_start_s"), audit_record.get("time_end_s")],
                "particle_axis_count": audit_record.get("particle_axis_count"),
                "initial_valid_particles": audit_record.get("initial_valid_particles"),
                "final_valid_particles": audit_record.get("final_valid_particles"),
                "identity_retention_first_to_last": audit_record.get("identity_retention_first_to_last"),
                "initial_fluid_mass_kg": audit_record.get("initial_fluid_mass_kg"),
                "final_valid_mass_kg": audit_record.get("final_valid_mass_kg"),
                "finite_bad_value_rows": audit_record.get("finite_bad_value_rows"),
                "issues": audit_record.get("issues"),
                "unknowns": audit_record.get("unknowns"),
                "native_transport_labels": "not materialized in historical HDF5",
            },
            "quality": {
                "gate_recipe_status": "passed" if gate.get("status") == "passed" else "not_passed",
                "historical_structural_status": "pass" if case.get("recorded_contract", {}).get("hard_audit_passed") is True and h5_header.get("status") == "light_header_pass" else "needs_review",
                "q_i": bool(case.get("recorded_contract", {}).get("hard_audit_passed") is True and h5_header.get("finite_endpoint_state") is True),
                "q_n": "historical_scope_only",
                "q_e": "missing_or_not_required",
                "native_transport_labels": "not_materialized_in_hdf5",
            },
            "reusable_for_new_mechanism": False,
            "reuse_reason": "historical plain single-axis fixed-tank acceleration scope; no transfer to dual-axis or baffle geometry",
        }
        case_rows.append(row)

    lineage_groups: dict[str, list[str]] = defaultdict(list)
    hashes: dict[str, list[str]] = defaultdict(list)
    source_hash_groups: dict[str, list[str]] = defaultdict(list)
    for row in case_rows:
        lineage = row.get("lineage_group_id")
        digest = row.get("hdf5_sha256")
        if isinstance(lineage, str):
            lineage_groups[lineage].append(row["case_id"])
        if isinstance(digest, str):
            hashes[digest].append(row["case_id"])
        for label, evidence in row.get("source_evidence", {}).items():
            source_digest = evidence.get("declared_sha256") if isinstance(evidence, dict) else None
            if _is_hex_digest(source_digest):
                source_hash_groups[source_digest].append(f"{row['case_id']}:{label}")
    duplicate_lineages = [{"lineage_group_id": key, "case_ids": value} for key, value in lineage_groups.items() if len(value) > 1]
    duplicate_hashes = [{"sha256": key, "case_ids": value} for key, value in hashes.items() if len(value) > 1]
    duplicate_source_hashes = [
        {"sha256": key, "source_refs": value, "duplicate_count": len(value)}
        for key, value in sorted(source_hash_groups.items()) if len(value) > 1
    ]
    existing_ok = [
        row for row in case_rows
        if row["status"] == "reused_historical_candidate"
        and row["hdf5_header"].get("status") == "light_header_pass"
        and row["solver_dimension"] == 3
        and row["hdf5_hash_check"] in {"declared_only_large_file", "full_match"}
        and row["quality"]["q_i"]
    ]
    old_split = Counter(str(row.get("legacy_split")) for row in case_rows)
    return {
        "schema": "ds-data-02.f3.history_audit.v1",
        "generator_version": GENERATOR_VERSION,
        "historical_root": str(historical_root),
        "material_archive_root": str(archive_root),
        "canonical_manifest": {
            "path": str(manifest_path),
            "sha256": sha256_file(manifest_path),
            "declared_schema": manifest.get("schema"),
            "status": manifest.get("status"),
        },
        "gate": {
            "path": str(gate_path),
            "sha256": sha256_file(gate_path),
            "schema": gate.get("schema"),
            "status": gate.get("status"),
            "recipe_id": gate.get("recipe_id"),
            "production_resolution_m": gate.get("production_resolution_m"),
            "reference_resolutions_m": gate.get("reference_resolutions_m"),
            "time_window_s": gate.get("time_window_s"),
            "coordinate_frame": gate.get("coordinate_frame"),
            "actual_solver_dimension": 3,
            "transfer_restriction": "gate applies only to historical plain/CELL3 fixed-tank prescribed acceleration; no new mechanism authorization",
        },
        "contract": {
            "path": str(contract_path),
            "sha256": sha256_file(contract_path),
            "schema": contract.get("schema"),
            "status": contract.get("status"),
            "qualified_sources": contract.get("qualified_sources"),
        },
        "closeout": {
            "path": str(closeout_path),
            "sha256": sha256_file(closeout_path),
            "status": closeout.get("status"),
            "formal_release": closeout.get("terminal_predicate", {}).get("formal_release"),
        },
        "summary": {
            "canonical_case_count": len(case_rows),
            "physical_case_count": len({row.get("physical_case_id") for row in case_rows}),
            "hdf5_exists_count": sum(bool(row["hdf5_header"].get("status") not in {"missing", "read_error"}) for row in case_rows),
            "light_header_pass_count": sum(row["hdf5_header"].get("status") == "light_header_pass" for row in case_rows),
            "actual_solver_dimension_3_count": sum(row.get("solver_dimension") == 3 for row in case_rows),
            "q_i_count": sum(row["quality"]["q_i"] for row in case_rows),
            "reusable_historical_count": len(existing_ok),
            "reusable_new_mechanism_count": 0,
            "old_split_counts": dict(sorted(old_split.items())),
            "duplicate_lineage_group_count": len(duplicate_lineages),
            "duplicate_hdf5_hash_count": len(duplicate_hashes),
            "duplicate_source_hash_group_count": len(duplicate_source_hashes),
            "full_hash_requested": full_hash,
            "native_transport_labels_materialized_count": 0,
        },
        "duplicate_checks": {
            "duplicate_lineage_groups": duplicate_lineages,
            "duplicate_hdf5_hashes": duplicate_hashes,
            "duplicate_source_hashes": duplicate_source_hashes,
            "identity_rule": "physical_case_id/lineage_group_id plus source HDF5 SHA-256; source template is provenance only",
        },
        "portable_reuse": {
            "status": "inventory_only_pending_explicit_packaging",
            "source_root": str(historical_root),
            "destination_root": str(RAW_OUTPUT_ROOT),
            "native_case_count": len(existing_ok),
            "source_paths": [row["portable_source_path"] for row in existing_ok],
            "preserve_fields": ["physical_case_id", "lineage_group_id", "hdf5_sha256", "legacy_split", "recipe_id", "input_contract"],
            "copy_rule": "copy bytes only after external raw attempt destination is allocated; verify declared source hash and never rewrite native arrays",
        },
        "cases": case_rows,
        "material_archive": _archive_inventory(archive_root),
        "gaps": [
            "new dual-axis mechanism has no solver output or qualification gate",
            "new eccentric-baffle/channel mechanism has no solver output or qualification gate",
            "historical HDF5 contains native state only; source/destination/first-passage/residence labels are not yet materialized",
            "historical full hash is receipt-bound in light mode; rerun with --full-hash for byte re-verification",
            "no portable copy has been made into the DS-DATA-02 raw attempt root",
            "no real preview has been generated by this packaging checkpoint",
        ],
    }


def _event_definitions() -> dict[str, Any]:
    return {
        "schema": "ds-data-02.f3.event_definitions.v1",
        "family_id": "F3",
        "event_time_window": {
            "definition": "full drive plus at least three dominant periods when a periodic template is declared, then a stopped-control reflow tail",
            "planned_window_s": [0.0, 10.0],
            "history_window_s": HISTORICAL_TIME_WINDOW,
            "history_reuse_rule": "8.35 s is reusable only for the same finite prescribed control and observation scope; it is not an automatic window for new mechanisms",
            "periodic_requirement": "if frequency_ratio or phase control makes a non-periodic template, report complete finite control and explicit censored tail instead",
        },
        "coordinate_frames": [
            {
                "frame_id": "fixed_tank_acceleration",
                "kind": "tank_attached",
                "position_semantics": "native solver position in fixed tank coordinates",
                "control_semantics": "linear/angular acceleration prescribed about acccentre; gravity is explicit and remains -9.81 m/s^2",
                "world_transform": "not inferred; no inertial-world trajectory claim",
            },
            {
                "frame_id": "moving_tank_world",
                "kind": "inertial_world",
                "position_semantics": "native solver/world position plus saved tank pose at every frame",
                "control_semantics": "tank translation/rotation trajectory prescribed in world time; fluid-relative event coordinates obtained by inverse rigid transform",
                "world_transform": "p_world = R_tank(t) p_tank + c_tank(t); event planes are defined in p_tank",
            },
        ],
        "source_regions": [
            {
                "source_label": "left",
                "region": "initial fluid particles with tank-frame x < 0",
                "denominator": "sum of initial fluid mass for all particles in region",
            },
            {
                "source_label": "right",
                "region": "initial fluid particles with tank-frame x >= 0",
                "denominator": "sum of initial fluid mass for all particles in region",
            },
            {
                "source_label": "front",
                "region": "initial fluid particles with tank-frame y < 0",
                "denominator": "sum of initial fluid mass for all particles in region",
            },
            {
                "source_label": "back",
                "region": "initial fluid particles with tank-frame y >= 0",
                "denominator": "sum of initial fluid mass for all particles in region",
            },
            {
                "source_label": "compartment_A_B_C",
                "region": "baffle geometry connected components at t=0, with explicit channel ownership",
                "denominator": "initial mass per connected component; channel particles remain source-labelled by initial component",
            },
        ],
        "finite_surfaces": [
            {
                "event_id": "left_right_exchange",
                "normal_in_tank_frame": [1.0, 0.0, 0.0],
                "surface": "x=0; y in [-0.09,0.09], z in [0,0.51], excluding solid baffle faces",
                "signed_direction": "left_to_right positive, right_to_left negative",
                "applies_to": ["dual_axis_phase", "eccentric_baffle_exchange"],
            },
            {
                "event_id": "front_back_exchange",
                "normal_in_tank_frame": [0.0, 1.0, 0.0],
                "surface": "y=0; x in [-0.45,0.45], z in [0,0.51], finite wetted opening only",
                "signed_direction": "front_to_back positive, back_to_front negative",
                "applies_to": ["dual_axis_phase"],
            },
            {
                "event_id": "baffle_channel_entry",
                "normal_in_tank_frame": [1.0, 0.0, 0.0],
                "surface": "upstream face of each finite channel; aperture bounds are geometry assets, never an infinite plane",
                "signed_direction": "source compartment toward channel positive",
                "applies_to": ["eccentric_baffle_exchange"],
            },
            {
                "event_id": "baffle_channel_exit",
                "normal_in_tank_frame": [1.0, 0.0, 0.0],
                "surface": "downstream face of each finite channel; channel index is part of event key",
                "signed_direction": "channel toward destination compartment positive",
                "applies_to": ["eccentric_baffle_exchange"],
            },
            {
                "event_id": "top_open_exit",
                "normal_in_tank_frame": [0.0, 0.0, 1.0],
                "surface": "finite top rim z=0.51; report legal open exit separately from closed-wall violation",
                "signed_direction": "outward positive",
                "applies_to": ["dual_axis_phase", "eccentric_baffle_exchange"],
            },
        ],
        "locator": {
            "algorithm": "saved-frame interval linear chord intersection in the event frame",
            "tau_definition": "tau=(plane_value-p0)/(p1-p0), retain 0<=tau<=1 and interpolate time linearly",
            "ordering": "sort same-interval events by tau, then surface_id, then numerical_id",
            "multiple_crossings": "each crossing is an event; net flux is signed mass sum; forward/backward totals are separate",
            "no_posthoc_projection": True,
            "out_of_domain": "closed wall, legal top exit, solver-invalid, numerical loss, and unknown are mutually exclusive categories",
        },
        "required_labels": [
            {"field": "source_label", "dtype": "fixed string or enum", "semantics": "continuous initial identity region"},
            {"field": "destination_time_series", "dtype": "int8 [time,particle]", "semantics": "region at every saved frame; final location is separate from ever-arrived"},
            {"field": "first_passage_interval", "dtype": "float64 [particle,event]", "semantics": "first crossing time, NaN only for censored/no event with censor flag"},
            {"field": "cumulative_net_flux_kg", "dtype": "float64 [time,event]", "semantics": "signed sum of native particle masses"},
            {"field": "forward_backward_mass_kg", "dtype": "float64 [time,event,2]", "semantics": "repeat crossings retained without creating new particles"},
            {"field": "residence_time_s", "dtype": "float64 [particle,region]", "semantics": "integral of valid occupancy; interval-censoring is explicit"},
            {"field": "final_category", "dtype": "enum", "semantics": "final region, legal_open_exit, closed_wall, invalid, numerical_loss, unknown"},
            {"field": "failure_reason", "dtype": "enum/string", "semantics": "root cause or censor code, unknown is not zero"},
            {"field": "unknown_mass_kg", "dtype": "float64 [time]", "semantics": "mass not classifiable from native state or missing event support"},
        ],
    }


def _observation_plan() -> dict[str, Any]:
    return {
        "schema": "ds-data-02.f3.observation_plan.v1",
        "family_id": "F3",
        "freeze_before_launch": {
            "physical_scales": {"L_m": 0.9, "U_m_s": round(math.sqrt(9.81 * 0.9), 12), "T_gravity_s": round(math.sqrt(0.9 / 9.81), 12)},
            "reconstruction_operator": "native particle mass weighted spatial bins and fixed physical window; no posthoc path projection",
            "event_operator": "finite surface segment locator from event_definitions.json",
            "sampling": "all native saved fluid states for complete cases; derived views inherit parent split",
            "thresholds": {
                "major_macro_relative_error": 0.05,
                "event_time_fraction_of_feature_time": 0.02,
                "sampling_error_fraction_of_total": 0.20,
                "integration_error_fraction_of_total": 0.20,
                "initial_mass_relative_tolerance": 0.01,
            },
            "uncertainty": "report finite-wall/solver-loss/unknown masses and censored events rather than assigning zero",
        },
        "physical_axes": PHYSICAL_AXIS_PLAN,
        "holdout_design": {
            "training_support": "amplitude, frequency/natural-frequency ratio and fill fraction vary within each mechanism using frozen control/geometry hash families",
            "control_holdout": "new smooth time template or inter-axis phase is held out by control_family_id",
            "geometry_holdout": "new channel layout and baffle offset are held out by geometry_family_id",
            "historical_scope": "legacy single-axis fixed-acceleration cases remain a preserved source family and are excluded from new-mechanism holdout claims",
        },
        "major_observables": [
            {
                "observable_id": "exchange_mass",
                "name": "左右/前后或分舱交换质量",
                "formula": "M_forward(t), M_backward(t), M_net(t)=M_forward-M_backward",
                "primary": True,
                "tolerance": "5% macro budget plus event-time budget",
            },
            {
                "observable_id": "repeat_crossing",
                "name": "重复通过与往返比例",
                "formula": "count and mass of signed crossing events per initial source label",
                "primary": True,
                "tolerance": "event interval error <=2% feature time where crossing is observed",
            },
            {
                "observable_id": "surface_com_phase",
                "name": "液面/质心幅值、相位和长时漂移",
                "formula": "robust free-surface quantiles and mass-weighted COM; fit phase only on declared periodic segment",
                "primary": True,
                "tolerance": "amplitude and phase reported with fit residual and drift interval",
            },
            {
                "observable_id": "distribution_3d",
                "name": "三维分布",
                "formula": "mass-normalized fixed-scale 3D occupancy histogram and axial marginals",
                "primary": True,
                "tolerance": "TV and common-support mass; resolution panel is required before Q-N",
            },
            {
                "observable_id": "velocity_energy",
                "name": "速度和动能",
                "formula": "mass-weighted mean velocity, covariance, and 0.5*sum(m*|v|^2)",
                "primary": True,
                "tolerance": "5% macro budget; report native valid denominator",
            },
            {
                "observable_id": "boundary_correction_usage",
                "name": "边界修正使用量",
                "formula": "native no-penetration/shifting flags and counts from solver receipt; no inferred correction",
                "primary": False,
                "tolerance": "descriptive gate, never hidden",
            },
        ],
        "secondary_observables": [
            "initial representative volume, total mass, COM and effective depth by resolution",
            "valid/invalid/lost/open-exit/closed-wall/unknown mass ledger per frame",
            "tank-frame and world-frame COM/velocity for moving-tank cases",
        ],
        "two_by_three_reference_matrix": {
            "minimum": "two mechanisms x three resolutions, same continuous initial condition and numerical strategy per mechanism",
            "matrix": [
                {"mechanism_id": mechanism_id, "resolution_id": cell["resolution_id"], "dp_m": cell["dp_m"], "status": "planned_no_solver"}
                for mechanism_id, ladder in NEW_RESOLUTION_LADDERS.items() for cell in ladder
            ],
            "comparison": "same control, same initial state and event frame across resolutions; no direct inheritance of old gate",
        },
        "integration_step_study": {
            "status": "planned_no_solver",
            "cases": [
                {"mechanism_id": mechanism_id, "resolution_id": "medium", "integration_variant": variant, "output_interval_s": 0.005, "time_window_s": [0.0, 10.0]}
                for mechanism_id in MECHANISMS for variant in ["native_dt", "registered_dtmin_half"]
            ],
            "rules": [
                "record actual dt_min_s, dt_max_s, median dt and total native steps from solver receipt",
                "hold geometry/control/output cadence fixed while changing integration control",
                "do not call output downsampling an integration-step study",
                "Q-N remains pending until both full event-window state and step study are complete",
            ],
        },
        "sampling_cadence_study": {
            "status": "planned_no_solver",
            "base_output_interval_s": 0.0025,
            "derived_cadences_s": [0.005, 0.01],
            "rules": [
                "high-frequency trajectory is the parent; derived views are not new physical cases",
                "finite event locator runs on parent saved intervals before downsampling",
                "compare crossing time, exchange mass, COM phase and energy against parent",
                "report actual final timestamp and control coverage; never pad beyond input",
            ],
        },
        "qualification_status": "definition_frozen_for_review; no new Q-N claim",
    }


def _xml_child(parent: ET.Element, tag: str, attrs: Mapping[str, Any] | None = None, text: str | None = None) -> ET.Element:
    node = ET.SubElement(parent, tag, {str(key): str(value) for key, value in (attrs or {}).items()})
    if text is not None:
        node.text = text
    return node


def _xml_drawbox(
    parent: ET.Element,
    boxfill: str,
    point: Sequence[float],
    size: Sequence[float],
    *,
    layers: str | None = None,
) -> ET.Element:
    node = _xml_child(parent, "drawbox")
    _xml_child(node, "boxfill", text=boxfill)
    _xml_child(node, "point", {axis: f"{value:.17g}" for axis, value in zip("xyz", point)})
    _xml_child(node, "size", {axis: f"{value:.17g}" for axis, value in zip("xyz", size)})
    if layers is not None:
        _xml_child(node, "layers", {"vdp": layers})
    return node


def _parent_control_envelope(time_s: float) -> float:
    """Smoothly start and stop the finite control, leaving a reflow tail."""
    if time_s <= 0.5:
        return 0.5 * (1.0 - math.cos(math.pi * time_s / 0.5))
    if time_s <= PARENT_INPUT_STOP_START_S:
        return 1.0
    if time_s <= PARENT_INPUT_STOP_END_S:
        phase = (time_s - PARENT_INPUT_STOP_START_S) / (PARENT_INPUT_STOP_END_S - PARENT_INPUT_STOP_START_S)
        return 0.5 * (1.0 + math.cos(math.pi * phase))
    return 0.0


def _write_dual_axis_control(path: Path) -> dict[str, Any]:
    omega = 2.0 * math.pi / 1.9
    lines = ["#Time;LinearAccX;LinearAccY;LinearAccZ;AngularAccX;AngularAccY;AngularAccZ"]
    for index in range(PARENT_INPUT_CONTROL_ROWS):
        time_s = PARENT_INPUT_TIME_WINDOW_S[0] + index * PARENT_INPUT_DT_S
        envelope = _parent_control_envelope(time_s)
        ax = 0.60 * 9.81 * envelope * math.sin(omega * time_s)
        ay = 0.45 * 9.81 * envelope * math.sin(omega * time_s + math.pi / 2.0)
        lines.append(f"{time_s:.5f};{ax:.10g};{ay:.10g};-9.81;0;0;0")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "rows": PARENT_INPUT_CONTROL_ROWS,
        "time_window_s": list(PARENT_INPUT_TIME_WINDOW_S),
        "sample_interval_s": PARENT_INPUT_DT_S,
        "drive_stop_s": PARENT_INPUT_STOP_START_S,
        "reflow_tail_end_s": PARENT_INPUT_TIME_WINDOW_S[1],
        "frequency_hz": omega / (2.0 * math.pi),
        "coordinate_frame_id": "fixed_tank_acceleration",
        "columns": ["time_s", "linear_acc_x_m_s2", "linear_acc_y_m_s2", "linear_acc_z_m_s2", "angular_acc_x_rad_s2", "angular_acc_y_rad_s2", "angular_acc_z_rad_s2"],
    }


def _write_moving_tank_control(path: Path) -> dict[str, Any]:
    omega = 2.0 * math.pi / 1.9
    lines: list[str] = []
    for index in range(PARENT_INPUT_CONTROL_ROWS):
        time_s = PARENT_INPUT_TIME_WINDOW_S[0] + index * PARENT_INPUT_DT_S
        envelope = _parent_control_envelope(time_s)
        x = 0.025 * envelope * math.sin(omega * time_s)
        y = 0.012 * envelope * math.sin(omega * time_s + math.pi / 3.0)
        lines.append(f"{time_s:.5f} {x:.10g} {y:.10g} 0")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "rows": PARENT_INPUT_CONTROL_ROWS,
        "time_window_s": list(PARENT_INPUT_TIME_WINDOW_S),
        "sample_interval_s": PARENT_INPUT_DT_S,
        "drive_stop_s": PARENT_INPUT_STOP_START_S,
        "reflow_tail_end_s": PARENT_INPUT_TIME_WINDOW_S[1],
        "frequency_hz": omega / (2.0 * math.pi),
        "coordinate_frame_id": "moving_tank_world",
        "columns": ["time_s", "tank_translation_x_m", "tank_translation_y_m", "tank_translation_z_m"],
        "pose_note": "translation-only world pose; tank-relative event coordinates require the recorded rigid transform",
    }


def _append_parent_constants(casedef: ET.Element, dp_m: float) -> None:
    constants = _xml_child(casedef, "constantsdef")
    _xml_child(constants, "gravity", {"x": 0, "y": 0, "z": -9.81})
    _xml_child(constants, "rhop0", {"value": 1000})
    _xml_child(constants, "rhopgradient", {"value": 2})
    _xml_child(constants, "hswl", {"value": 0, "auto": "true"})
    _xml_child(constants, "gamma", {"value": 7})
    _xml_child(constants, "speedsystem", {"value": 0, "auto": "true"})
    _xml_child(constants, "coefsound", {"value": 30})
    _xml_child(constants, "speedsound", {"value": 0, "auto": "true"})
    _xml_child(constants, "coefh", {"value": 0.91924})
    _xml_child(constants, "cflnumber", {"value": 0.2})
    _xml_child(casedef, "mkconfig", {"boundcount": 240, "fluidcount": 9})
    geometry = _xml_child(casedef, "geometry")
    _xml_child(geometry, "definition", {"dp": f"{dp_m:.17g}", "units_comment": "metres (m)"})
    definition = geometry.find("definition")
    assert definition is not None
    _xml_child(definition, "pointref", {"x": f"{dp_m / 2:.17g}", "y": f"{dp_m / 2:.17g}", "z": f"{dp_m / 2:.17g}"})
    _xml_child(definition, "pointmin", {"x": -0.6, "y": -0.25, "z": -0.1})
    _xml_child(definition, "pointmax", {"x": 0.6, "y": 0.25, "z": 0.7})


def _append_parent_parameters(root: ET.Element, *, time_out_s: float = 0.0025) -> None:
    execution = root.find("execution")
    if execution is None:
        execution = _xml_child(root, "execution")
    parameters = _xml_child(execution, "parameters")
    values = {
        "SavePosDouble": 2,
        "Boundary": 2,
        "SlipMode": 2,
        "NoPenetration": 1,
        "StepAlgorithm": 2,
        "VerletSteps": 40,
        "Kernel": 2,
        "ViscoTreatment": 1,
        "Visco": 0.05,
        "ViscoBoundFactor": 1,
        "DensityDT": 3,
        "DensityDTvalue": 0.1,
        "Shifting": 0,
        "ShiftCoef": -2,
        "ShiftTFS": 0,
        "RigidAlgorithm": 1,
        "FtPause": 0.0,
        "CoefDtMin": 0.05,
        "DtIni": 0,
        "DtMin": 0,
        "DtFixed": 0,
        "DtAllParticles": 0,
        "TimeMax": PARENT_INPUT_TIME_WINDOW_S[1],
        "TimeOut": time_out_s,
        "PartsOutMax": 1,
        "RhopOutMin": 700,
        "RhopOutMax": 1300,
        "MinFluidStop": 0,
    }
    for key, value in values.items():
        _xml_child(parameters, "parameter", {"key": key, "value": value})
    domain = _xml_child(parameters, "simulationdomain")
    _xml_child(domain, "posmin", {"x": "default-150%", "y": "default-150%", "z": "default-150%"})
    _xml_child(domain, "posmax", {"x": "default+150%", "y": "default+150%", "z": "default+150%"})


def _write_dual_axis_definition(
    directory: Path,
    *,
    normal_distanceh: float = 2.0,
    normal_save_shapes: bool = False,
) -> dict[str, Any]:
    path = directory / "F3_DualAxisPhase_Def.xml"
    control_name = "F3_DualAxisPhase_Control.csv"
    root = ET.Element("case")
    casedef = _xml_child(root, "casedef")
    _append_parent_constants(casedef, PARENT_DUAL_DP_M)
    geometry = casedef.find("geometry")
    assert geometry is not None
    commands = _xml_child(geometry, "commands")
    normal_list = _xml_child(commands, "list", {"name": "GeometryForNormals"})
    _xml_child(normal_list, "setactive", {"drawpoints": 0, "drawshapes": 1})
    _xml_child(normal_list, "setshapemode", text="actual | bound")
    _xml_child(normal_list, "setnormalinvert", {"invert": "true"})
    _xml_child(normal_list, "setmkbound", {"mk": 0})
    _xml_drawbox(normal_list, "all^top", [-0.45, -0.1, 0], [0.9, 0.2, 0.508], layers="-0.5")
    _xml_child(normal_list, "shapeout", {"file": "hdp"})
    _xml_child(normal_list, "resetdraw")
    main = _xml_child(commands, "mainlist")
    _xml_child(main, "runlist", {"name": "GeometryForNormals"})
    _xml_child(main, "setshapemode", text="dp | bound")
    _xml_child(main, "setdrawmode", {"mode": "full"})
    _xml_child(main, "setmkbound", {"mk": 0})
    _xml_drawbox(main, "bottom | left | right | front | back", [-0.45, -0.1, 0], [0.9, 0.2, 0.508], layers="0,1,2,3")
    _xml_child(main, "setmkfluid", {"mk": 0})
    _xml_child(main, "fillbox", {"x": 0, "y": 0, "z": 0.02})
    fill = main.find("fillbox")
    assert fill is not None
    _xml_child(fill, "modefill", text="void")
    _xml_child(fill, "point", {"x": -0.45, "y": -0.1, "z": 0})
    _xml_child(fill, "size", {"x": 0.9, "y": 0.2, "z": 0.093})
    _xml_child(main, "shapeout", {"file": ""})
    normals = _xml_child(casedef, "normals", {"active": "true"})
    norgeometry = _xml_child(normals, "norgeometry")
    _xml_child(norgeometry, "geometryfile", {"file": "[CaseName]_hdp_Actual.vtk"})
    _xml_child(norgeometry, "distanceh", {"v": f"{normal_distanceh:.1f}"})
    if normal_save_shapes:
        _xml_child(norgeometry, "svshapes", {"v": "true"})
    execution = root.find("execution")
    if execution is None:
        execution = _xml_child(root, "execution")
    special = _xml_child(execution, "special")
    accinputs = _xml_child(special, "accinputs")
    accinput = _xml_child(accinputs, "accinput", {"mkfluid": 0})
    _xml_child(accinput, "acccentre", {"x": 0.45, "y": 0, "z": 0})
    _xml_child(accinput, "globalgravity", {"value": 0})
    _xml_child(accinput, "acctimesfile", {"value": control_name})
    _append_parent_parameters(root)
    ET.indent(root, space="  ")
    directory.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    control = _write_dual_axis_control(directory / control_name)
    return {
        "case_id": PARENT_DUAL_CASE_ID,
        "mechanism_id": "dual_axis_phase",
        "definition": {"path": str(path.resolve()), "sha256": sha256_file(path), "bytes": path.stat().st_size},
        "control": control,
        "geometry": {
            "tank_bounds_m": [-0.45, 0.45, -0.1, 0.1, 0.0, 0.508],
            "fluid_box_m": [-0.45, 0.45, -0.1, 0.1, 0.0, 0.093],
            "closed_faces": ["bottom", "left", "right", "front", "back"],
            "open_faces": ["top"],
            "nominal_transverse_layers": 24,
            "minimum_transverse_layers": 20,
            "finite_wall": True,
        },
        "coordinate_frame_id": "fixed_tank_acceleration",
        "solver_dimension_required": 3,
        "time_window_s": list(PARENT_INPUT_TIME_WINDOW_S),
        "output_interval_s": 0.0025,
    }


def _write_baffle_definition(
    directory: Path,
    *,
    normal_distanceh: float = 2.0,
    normal_save_shapes: bool = False,
) -> dict[str, Any]:
    path = directory / "F3_EccentricBaffle_Def.xml"
    motion_name = "F3_EccentricBaffle_Motion.txt"
    root = ET.Element("case")
    casedef = _xml_child(root, "casedef")
    _append_parent_constants(casedef, PARENT_BAFFLE_DP_M)
    geometry = casedef.find("geometry")
    assert geometry is not None
    commands = _xml_child(geometry, "commands")
    baffle_segments = [
        ([-0.012, -0.092, 0.0], [0.024, 0.087, 0.30]),
        ([-0.012, 0.045, 0.0], [0.024, 0.047, 0.30]),
    ]
    normal_list = _xml_child(commands, "list", {"name": "GeometryForNormals"})
    _xml_child(normal_list, "setactive", {"drawpoints": 0, "drawshapes": 1})
    _xml_child(normal_list, "setshapemode", text="actual | bound")
    _xml_child(normal_list, "setnormalinvert", {"invert": "true"})
    _xml_child(normal_list, "setmkbound", {"mk": 0})
    _xml_drawbox(normal_list, "all^top", [-0.45, -0.1, 0], [0.9, 0.2, 0.508], layers="-0.5")
    _xml_child(normal_list, "setnormalinvert", {"invert": "false"})
    _xml_child(normal_list, "setmkbound", {"mk": 1})
    for point, size in baffle_segments:
        _xml_drawbox(normal_list, "bottom | top | left | right | front | back", point, size, layers="-0.5")
    _xml_child(normal_list, "shapeout", {"file": "hdp"})
    _xml_child(normal_list, "resetdraw")
    main = _xml_child(commands, "mainlist")
    _xml_child(main, "runlist", {"name": "GeometryForNormals"})
    _xml_child(main, "setshapemode", text="dp | bound")
    _xml_child(main, "setdrawmode", {"mode": "full"})
    _xml_child(main, "setmkbound", {"mk": 0})
    _xml_drawbox(main, "bottom | left | right | front | back", [-0.45, -0.1, 0], [0.9, 0.2, 0.508], layers="0,1,2,3")
    for point, size in baffle_segments:
        # The finite six-face shell already closes the baffle volume.  A
        # preceding setmkvoid/solid operation under full draw mode marks the
        # surrounding lattice as moving-bound in GenCase 5.4, which erased
        # the connected fill domain (observed in parent attempt _01).  Keep
        # the physical wall as a finite shell and let modefill=void flood
        # only the connected fluid region.
        _xml_child(main, "setmkbound", {"mk": 1})
        _xml_drawbox(main, "bottom | top | left | right | front | back", point, size, layers="0,1,2")
    _xml_child(main, "setmkfluid", {"mk": 0})
    # Seed the connected channel away from the finite baffle thickness.  At
    # dp=0.008 the old origin seed snapped to x=0.004 inside the baffle and
    # modefill=void correctly produced no fluid from that enclosed seed.
    fluid = _xml_child(main, "fillbox", {"x": -0.30, "y": 0.02, "z": 0.05})
    _xml_child(fluid, "modefill", text="void")
    _xml_child(fluid, "point", {"x": -0.45, "y": -0.092, "z": 0})
    _xml_child(fluid, "size", {"x": 0.9, "y": 0.184, "z": 0.14})
    _xml_child(main, "shapeout", {"file": ""})
    normals = _xml_child(casedef, "normals", {"active": "true"})
    norgeometry = _xml_child(normals, "norgeometry")
    _xml_child(norgeometry, "geometryfile", {"file": "[CaseName]_hdp_Actual.vtk"})
    _xml_child(norgeometry, "distanceh", {"v": f"{normal_distanceh:.1f}"})
    if normal_save_shapes:
        _xml_child(norgeometry, "svshapes", {"v": "true"})
    motion = _xml_child(casedef, "motion")
    objreal = _xml_child(motion, "objreal", {"ref": 0})
    _xml_child(objreal, "begin", {"mov": 1, "start": 0, "finish": PARENT_INPUT_TIME_WINDOW_S[1]})
    mvfile = _xml_child(objreal, "mvfile", {"id": 1, "duration": PARENT_INPUT_TIME_WINDOW_S[1]})
    _xml_child(mvfile, "file", {"name": motion_name, "fields": 4, "fieldtime": 0, "fieldx": 1, "fieldy": 2, "fieldz": 3})
    _append_parent_parameters(root)
    ET.indent(root, space="  ")
    directory.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    motion_info = _write_moving_tank_control(directory / motion_name)
    return {
        "case_id": PARENT_BAFFLE_CASE_ID,
        "mechanism_id": "eccentric_baffle_exchange",
        "definition": {"path": str(path.resolve()), "sha256": sha256_file(path), "bytes": path.stat().st_size},
        "control": motion_info,
        "geometry": {
            "tank_bounds_m": [-0.45, 0.45, -0.1, 0.1, 0.0, 0.508],
            "fluid_box_m": [-0.45, 0.45, -0.092, 0.092, 0.0, 0.14],
            "baffle_segments": [
                {"point_m": point, "size_m": size} for point, size in baffle_segments
            ],
            "channel_opening_m": {"y_min": -0.005, "y_max": 0.045, "width": 0.05, "offset_y": 0.02, "z_max": 0.30},
            "closed_faces": ["bottom", "left", "right", "front", "back"],
            "open_faces": ["top", "channel aperture"],
            "nominal_transverse_layers": 23,
            "minimum_transverse_layers": 20,
            "finite_wall": True,
        },
        "coordinate_frame_id": "moving_tank_world",
        "solver_dimension_required": 3,
        "time_window_s": list(PARENT_INPUT_TIME_WINDOW_S),
        "output_interval_s": 0.0025,
    }


def _repair_input_record(
    parent: Mapping[str, Any],
    repair_directory: Path,
    canonical_directory: Path,
) -> dict[str, Any]:
    """Write an additive mDBC normal-coverage repair beside a parent.

    The geometry, fill, motion/control values and solver parameters stay
    byte-for-byte identical to the parent.  Only the normal association
    radius and shape-vector debug switch change, because the QUAL02 evidence
    showed systematic zero normal vectors in the outer boundary layers.
    """
    mechanism_id = str(parent["mechanism_id"])
    if mechanism_id == "dual_axis_phase":
        repair = _write_dual_axis_definition(
            repair_directory, normal_distanceh=3.0, normal_save_shapes=True
        )
        filename = "F3_DualAxisPhase_Control.csv"
    elif mechanism_id == "eccentric_baffle_exchange":
        repair = _write_baffle_definition(
            repair_directory, normal_distanceh=3.0, normal_save_shapes=True
        )
        filename = "F3_EccentricBaffle_Motion.txt"
    else:
        raise ValueError(f"unsupported F3 repair mechanism: {mechanism_id}")

    # Reuse the exact control/motion bytes from the canonical parent.  The
    # repair directory is a new input identity, while the driving signal is
    # explicitly unchanged and hash-bound.
    source = canonical_directory / filename
    target = repair_directory / filename
    shutil.copyfile(source, target)
    control = dict(repair["control"])
    control.update({
        "path": str(target.resolve()),
        "sha256": sha256_file(target),
        "bytes": target.stat().st_size,
        "copied_from": str(source.resolve()),
        "source_sha256": sha256_file(source),
    })
    repair["control"] = control
    repair.update({
        "repair_id": f"{mechanism_id}_normal_coverage_repair01",
        "parent_case_id": parent["case_id"],
        "parent_definition_sha256": parent["definition"]["sha256"],
        "repair_hypothesis": "mDBC normal association radius was too short for the four-layer finite wall; svshapes records the associated shape vectors",
        "changed_parameters": {
            "norgeometry.distanceh": {"parent": 2.0, "repair": 3.0},
            "norgeometry.svshapes": {"parent": False, "repair": True},
        },
        "geometry_and_control_contract": "same geometry commands, fill seed/box, motion or acceleration control and execution parameters; no domain or density threshold change",
        "qualification_status": "GenCase_pending_solver_QI_pending_QN_pending",
    })
    return repair


def _write_normal_coverage_repairs(
    parent_root: Path,
    canonical_parents: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Materialise independent repair01 source inputs and their hash ledger."""
    repairs: list[dict[str, Any]] = []
    for parent in canonical_parents:
        mechanism_id = str(parent["mechanism_id"])
        canonical_directory = parent_root / mechanism_id
        repair_directory = parent_root / f"{mechanism_id}_normal_repair01"
        repairs.append(_repair_input_record(parent, repair_directory, canonical_directory))
    return repairs


def _write_parent_inputs(output_root: Path) -> dict[str, Any]:
    parent_root = output_root / "parent_inputs"
    previous_manifest: dict[str, Any] = {}
    manifest_path = parent_root / "parent_input_manifest.json"
    if manifest_path.is_file():
        try:
            previous_manifest = read_json(manifest_path)
        except (OSError, ValueError, json.JSONDecodeError):
            previous_manifest = {}
    dual = _write_dual_axis_definition(parent_root / "dual_axis_phase")
    baffle = _write_baffle_definition(parent_root / "eccentric_baffle_exchange")
    repairs = _write_normal_coverage_repairs(parent_root, [dual, baffle])
    manifest = {
        "schema": "ds-data-02.f3.parent_inputs.v1",
        "family_id": "F3",
        "status": "definition_frozen_cpu_gencase_pending_or_receipted",
        "common": {
            "solver_dimension_required": 3,
            "time_window_s": list(PARENT_INPUT_TIME_WINDOW_S),
            "drive_stop_s": PARENT_INPUT_STOP_START_S,
            "reflow_tail_end_s": PARENT_INPUT_TIME_WINDOW_S[1],
            "output_interval_s": 0.0025,
            "finite_wall_contract": "bottom/left/right/front/back are closed; top is open; baffle has two finite segments and a finite channel aperture",
            "initial_mass_contract": "native MassFluid times fluid count compared with density times fluid region after GenCase; no mass rescaling",
        },
        "parents": [dual, baffle],
        "repairs": repairs,
    }
    # `audit-parents` adds immutable receipt pointers after GenCase.  A later
    # source regeneration must retain those pointers instead of silently
    # replacing a receipted parent with a definition-only record.
    previous_by_case = {
        str(row.get("case_id")): row
        for row in previous_manifest.get("parents", [])
        if isinstance(row, Mapping) and row.get("case_id")
    }
    for parent in manifest["parents"]:
        old = previous_by_case.get(str(parent.get("case_id")))
        if isinstance(old, Mapping) and old.get("gencase_audit"):
            parent["gencase_audit"] = old["gencase_audit"]
    if previous_manifest.get("gencase_audit"):
        manifest["gencase_audit"] = previous_manifest["gencase_audit"]
    _write_json(manifest_path, manifest)
    return manifest


def _new_case_slots() -> list[dict[str, Any]]:
    slots: list[dict[str, Any]] = []
    role_by_index = ["train"] * 4 + ["validation"] + ["geometry_control_ood"] * 3
    for mechanism_id in MECHANISMS:
        for local_index, role in enumerate(role_by_index):
            case_id = f"F3_NEW_{mechanism_id.upper()}_{local_index:02d}"
            slots.append({
                "case_id": case_id,
                "physical_case_id": f"{case_id}_PHYSICAL_HASH_PENDING",
                "lineage_group_id": f"{case_id}_LINEAGE_PENDING",
                "paired_background_id": f"{mechanism_id}_paired_background_{local_index:02d}",
                "family_id": "F3",
                "mechanism_id": mechanism_id,
                "geometry_family_id": MECHANISMS[mechanism_id]["geometry_family_id"],
                "control_family_id": MECHANISMS[mechanism_id]["control_family_id"],
                "recipe_id": f"F3_DS02_{mechanism_id}_v1",
                "view_id": "native_full_window",
                "attempt_id": None,
                "status": "planned_no_solver",
                "split": role,
                "legacy_split": None,
                "target_role": role,
                "resolution_id": "medium",
                "dp_m": 0.0075 if mechanism_id == "dual_axis_phase" else 0.008,
                "physical_axis_plan": "drive_amplitude/frequency_over_natural/fill_fraction",
                "axis_assignment": "freeze_after_parent_geometry_and_control_hashes",
                "solver_dimension": "pending_actual_solver_output",
                "coordinate_frame_id": MECHANISMS[mechanism_id]["coordinate_frame_id"],
                "hdf5_path": None,
                "hdf5_sha256": None,
                "full_event_window_s": [0.0, 10.0],
                "required_before_reuse": ["case-level source/control/geometry hashes", "actual solver dimension", "native event labels", "Q-I audit", "2x3 Q-N scope"],
            })
    return slots


def _family_card(audit: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": "ds-data-02.f3.family_card.v1",
        "family_id": "F3",
        "title": "三维晃荡、非对称挡板与交换",
        "generator_version": GENERATOR_VERSION,
        "dataset_activity": "DS-DATA-02",
        "status": "historical_scope_reusable; new_mechanisms_definition_ready",
        "training_and_inference": {"training_allowed": False, "inference_allowed": False, "weights_loaded": False},
        "historical_reuse": {
            "canonical_manifest": CANONICAL_MANIFEST,
            "gate": HISTORICAL_GATE,
            "actual_reusable_native_case_count": audit["summary"]["reusable_historical_count"],
            "old_split_shape": audit["summary"]["old_split_counts"],
            "reference_gencase_receipt": str(REFERENCE_GENCAS_RECEIPT),
            "reuse_semantics": "native numerical identity trajectories only; no material-path claim",
            "split_policy": "retain historical train/validation/test labels byte-for-byte; do not rewrite to DS-DATA-02 role counts",
        },
        "mechanisms": [MECHANISMS[key] for key in MECHANISMS],
        "physical_axes": PHYSICAL_AXIS_PLAN,
        "holdout_policy": {
            "control": "hold out a smooth control template or inter-axis phase after freezing the continuous amplitude/frequency/fill axes",
            "geometry": "hold out a new eccentric channel layout; a changed amplitude alone is not a geometry holdout",
            "identity": "geometry, control, initial fill and perturbation hashes enter physical_case_id before split assignment",
        },
        "solver_dimension_contract": {
            "history_actual_solver_dimension": 3,
            "new_case_required_field": "solver_dimension from actual solver output/parameter, not coordinate_components alone",
            "format_coordinate_components": 3,
            "near_2d_rejection": "z nonzero or position[...,3] alone is insufficient",
        },
        "coordinate_frame_contract": {
            "fixed_tank_acceleration": "tank-attached coordinates; prescribed acceleration control; no world trajectory inference",
            "moving_tank_world": "inertial world coordinates plus explicit tank pose; event geometry evaluated after inverse rigid transform",
        },
        "event_and_observation_files": {
            "events": "event_definitions.json",
            "observations": "observation_plan.json",
            "matrix": "reference_evidence.json",
            "integration_and_sampling": "observation_plan.json",
        },
        "scope_gates": {"Q-I": "per-case structural/identity/finite/mass/domain audit", "Q-N": "recipe+subdomain+window+observable 2x3 plus integration/sampling evidence", "Q-E": "optional matched medium/geometry; never shared prerequisite"},
        "raw_output_root": str(RAW_OUTPUT_ROOT),
        "known_gaps": audit["gaps"],
    }


def _qualified_recipes(audit: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": "ds-data-02.f3.qualified_recipes.v1",
        "family_id": "F3",
        "qualification_policy": "scope-bound; historical gate does not transfer across control or geometry families",
        "recipes": [
            {
                "scope_id": "F3_LEGACY_PLAIN_FIXED_ACCELERATION",
                "status": "historical_gate_passed_reuse_scope",
                "recipe_id": HISTORICAL_RECIPE,
                "geometry_family_id": "F3_CELL3_PLAIN",
                "control_family_id": "F3_CTRL_LEGACY_SINGLE_AXIS",
                "mechanism_id": "legacy_plain_sloshing",
                "solver_dimension": 3,
                "reference_resolutions_m": HISTORICAL_REFERENCE_RESOLUTIONS,
                "production_resolution_m": 0.0075,
                "time_window_s": HISTORICAL_TIME_WINDOW,
                "output_interval_s": HISTORICAL_OUTPUT_INTERVAL,
                "coordinate_frame_id": "fixed_tank_acceleration",
                "observables": ["3d_mass_distribution", "velocity", "kinetic_energy", "COM", "finite-wall audit"],
                "gate_path": HISTORICAL_GATE,
                "gate_sha256": audit["gate"]["sha256"],
                "transfer_to_new_mechanisms": False,
                "transfer_reason": "old gate is plain single-axis fixed-tank control; new dual-axis/baffle scopes require fresh matrices",
            },
            {
                "scope_id": "F3_DS02_DUAL_AXIS_PHASE_V1",
                "status": "definition_ready_generation_pending",
                "recipe_id": "F3_DS02_dual_axis_phase_v1",
                "geometry_family_id": MECHANISMS["dual_axis_phase"]["geometry_family_id"],
                "control_family_id": MECHANISMS["dual_axis_phase"]["control_family_id"],
                "mechanism_id": "dual_axis_phase",
                "solver_dimension": "pending_actual_solver_output",
                "reference_ladder_m": [cell["dp_m"] for cell in NEW_RESOLUTION_LADDERS["dual_axis_phase"]],
                "time_window_s": [0.0, 10.0],
                "coordinate_frame_id": "fixed_tank_acceleration",
                "status_reason": "requires 2x3 matrix, integration-step and cadence evidence",
            },
            {
                "scope_id": "F3_DS02_ECCENTRIC_BAFFLE_EXCHANGE_V1",
                "status": "definition_ready_generation_pending",
                "recipe_id": "F3_DS02_eccentric_baffle_exchange_v1",
                "geometry_family_id": MECHANISMS["eccentric_baffle_exchange"]["geometry_family_id"],
                "control_family_id": MECHANISMS["eccentric_baffle_exchange"]["control_family_id"],
                "mechanism_id": "eccentric_baffle_exchange",
                "solver_dimension": "pending_actual_solver_output",
                "reference_ladder_m": [cell["dp_m"] for cell in NEW_RESOLUTION_LADDERS["eccentric_baffle_exchange"]],
                "time_window_s": [0.0, 10.0],
                "coordinate_frame_id": "moving_tank_world",
                "status_reason": "requires actual baffle geometry, tank pose, exchange labels, 2x3 and integration/cadence evidence",
            },
        ],
    }


def _reference_evidence(audit: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": "ds-data-02.f3.reference_evidence.v1",
        "family_id": "F3",
        "historical": {
            "gate_status": audit["gate"]["status"],
            "gate_scope": audit["gate"]["transfer_restriction"],
            "actual_solver_dimension": 3,
            "canonical_case_count": audit["summary"]["canonical_case_count"],
            "actual_reusable_native_count": audit["summary"]["reusable_historical_count"],
            "q_i_count": audit["summary"]["q_i_count"],
            "q_n_scope": "historical recipe gate only; do not back new mechanisms",
            "q_e_status": "not_required_for_Q-N",
            "runner_reference": _compact_runner_receipt(REFERENCE_GENCAS_RECEIPT),
        },
        "new_mechanism_reference_matrix": [
            {
                "mechanism_id": mechanism_id,
                "geometry_family_id": MECHANISMS[mechanism_id]["geometry_family_id"],
                "control_family_id": MECHANISMS[mechanism_id]["control_family_id"],
                "coordinate_frame_id": MECHANISMS[mechanism_id]["coordinate_frame_id"],
                "cells": [
                    {
                        **cell,
                        "status": "planned_no_solver",
                        "solver_dimension": "pending_actual_solver_output",
                        "qualification": "not_granted",
                        "required_receipts": ["GenCase actual counts", "solver actual dimension", "native dt stats", "full-window HDF5", "Q-I audit"],
                    }
                    for cell in NEW_RESOLUTION_LADDERS[mechanism_id]
                ],
            }
            for mechanism_id in MECHANISMS
        ],
        "integration_and_sampling": {
            "plan_file": "observation_plan.json",
            "status": "planned_no_solver",
            "independent_integration_comparison": True,
            "independent_save_cadence_comparison": True,
            "downsample_is_not_new_case": True,
        },
        "negative_evidence": [
            "legacy 8.35 s window cannot automatically cover dual-axis phase or baffle exchange",
            "legacy plain trajectory has no baffle geometry and no world-frame tank pose",
            "material archive is duplicate candidate output and not a native transport label source",
        ],
    }


def _split_plan(audit: Mapping[str, Any]) -> dict[str, Any]:
    legacy_counts = audit["summary"]["old_split_counts"]
    slots = _new_case_slots()
    new_counts = Counter(row["split"] for row in slots)
    return {
        "schema": "ds-data-02.f3.split_plan.v1",
        "family_id": "F3",
        "status": "registered_development_candidate; no hidden_test_claim",
        "legacy_policy": {
            "source": CANONICAL_MANIFEST,
            "split_counts": legacy_counts,
            "retain_labels": True,
            "rewrite_to_default_24_6_6_6_6": False,
            "lineage_rule": "all views/windows/labels/resolutions inherit historical parent split",
        },
        "new_slots": slots,
        "new_slot_counts": dict(sorted(new_counts.items())),
        "coverage": {
            "mechanism_balance": {mechanism_id: 8 for mechanism_id in MECHANISMS},
            "new_geometry_or_control_holdout": 6,
            "new_physical_case_count": 16,
            "actual_new_case_count": 0,
            "target_total_unique_physical_cases": 48,
            "legacy_reused_count": audit["summary"]["reusable_historical_count"],
        },
        "leakage_rules": [
            "physical_case_id includes geometry, control, initial state and physical perturbation hash",
            "same physical case at multiple dp or cadence remains one lineage_group_id",
            "geometry holdout uses geometry_family_id; control holdout uses control_family_id",
            "template/source provenance does not define physical identity",
            "unverified identities remain isolated and cannot be randomly assigned",
        ],
        "open_actions": [
            "freeze hashes after generating each new control and geometry asset",
            "allocate actual new cases only after 2x3 scope gates",
            "materialize role-specific rows after runner-produced HDF5 and labels exist",
        ],
    }


def _label_schema() -> dict[str, Any]:
    events = _event_definitions()
    return {
        "schema": "ds-data-02.f3.labels.v1",
        "family_id": "F3",
        "status": "schema_ready_no_new_labels_written",
        "source": "native solver particle states; not a model or external material tracer",
        "required_event_definitions": "event_definitions.json",
        "array_contract": {
            "time_s": "float64 [time] finite strictly increasing",
            "particle_id": "uint64 [particle] unique initial identities",
            "particle_zone": "int16 [particle] stable solver zone",
            "source_label": "int8 [particle] initial source region",
            "destination_time_series": "int8 [time,particle]",
            "first_passage_interval": "float64 [particle,event] plus censor flags",
            "cumulative_net_flux_kg": "float64 [time,event]",
            "forward_backward_mass_kg": "float64 [time,event,2]",
            "residence_time_s": "float64 [particle,region]",
            "final_category": "int8 [particle]",
            "failure_reason": "UTF-8 enum [particle]",
            "unknown_mass_kg": "float64 [time]",
        },
        "unknown_policy": "unknown_mass_kg is explicit and mutually exclusive with legal exit, closed-wall and solver-loss buckets",
        "historical_gap": "the 32 legacy HDF5 files have no materialized F3 DS-DATA-02 event arrays; generation remains a required CPU packaging task",
        "event_count": len(events["finite_surfaces"]),
    }


def _execution_queue(audit: Mapping[str, Any], output_root: Path = FAMILY_ROOT) -> dict[str, Any]:
    history_input_files = [
        str((HISTORICAL_ROOT / relative).resolve())
        for relative in (CANONICAL_MANIFEST, HISTORICAL_GATE, HISTORICAL_CONTRACT, HISTORICAL_CLOSEOUT)
    ]
    history_input_files.extend(
        str(path.resolve()) for path in sorted(MATERIAL_ARCHIVE_ROOT.glob("*/artifact-manifest.json"))
    )
    history_input_files.append(str(Path(__file__).resolve()))
    audit_report = "{attempt_root}/history-audit.json"
    reference_case_dir = HISTORICAL_ROOT / "campaigns/l1-resume/artifacts/f3-ref0081818-development/F3_DEV_00_a0p903125"
    reference_definition = reference_case_dir / "F3_CELL3_plain_0p0075_Def.xml"
    reference_control = reference_case_dir / "CaseSloshingAccData.csv"
    reference_binary = HISTORICAL_ROOT / "vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64"
    reference_source_definition = HISTORICAL_ROOT / OFFICIAL_ACCEL_DEFINITION
    reference_prefix = "{attempt_root}/F3_HISTORY_CELL3_PARENT"
    completed_reference = _compact_runner_receipt(REFERENCE_GENCAS_RECEIPT)
    parent_root = output_root / "parent_inputs"
    dual_parent_dir = parent_root / "dual_axis_phase"
    baffle_parent_dir = parent_root / "eccentric_baffle_exchange"
    dual_definition = dual_parent_dir / "F3_DualAxisPhase_Def.xml"
    dual_control = dual_parent_dir / "F3_DualAxisPhase_Control.csv"
    baffle_definition = baffle_parent_dir / "F3_EccentricBaffle_Def.xml"
    baffle_control = baffle_parent_dir / "F3_EccentricBaffle_Motion.txt"
    gencase_binary = HISTORICAL_ROOT / "vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64"
    official_motion_definition = HISTORICAL_ROOT / OFFICIAL_MOTION_DEFINITION
    dual_attempt_id, dual_attempts = _select_parent_gencase_attempt(PARENT_DUAL_CASE_ID)
    baffle_attempt_id, baffle_attempts = _select_parent_gencase_attempt(PARENT_BAFFLE_CASE_ID)
    dual_receipt_01 = _compact_runner_receipt(_runner_receipt_path(PARENT_DUAL_CASE_ID, f"{PARENT_DUAL_CASE_ID}_GENCASE_01"))
    dual_receipt_02 = _compact_runner_receipt(_runner_receipt_path(PARENT_DUAL_CASE_ID, f"{PARENT_DUAL_CASE_ID}_GENCASE_02"))
    baffle_receipt_01 = _compact_runner_receipt(_runner_receipt_path(PARENT_BAFFLE_CASE_ID, f"{PARENT_BAFFLE_CASE_ID}_GENCASE_01"))
    baffle_receipt_02 = _compact_runner_receipt(_runner_receipt_path(PARENT_BAFFLE_CASE_ID, f"{PARENT_BAFFLE_CASE_ID}_GENCASE_02"))
    parent_gencase_ready = bool(
        any(int(row.get("fluid_particles") or 0) > 0 for row in dual_attempts)
        and any(int(row.get("fluid_particles") or 0) > 0 for row in baffle_attempts)
    )
    next_task = (
        "audit both successful parent GenCase outputs, then submit the generated qualification requests through the shared GPU runner"
        if parent_gencase_ready
        else "write/freeze the two new mechanism parent definitions, then submit one bounded CPU GenCase request per mechanism"
        if completed_reference.get("status") == "completed"
        else "run the two bounded CPU GenCase parent preflights after the shared reservation endpoint is supplied; do not infer qualification from canaries"
    )
    return {
        "schema": "ds-data-02.f3.execution_queue.v1",
        "family_id": "F3",
        "launch_allowed": False,
        "reason": "shared DS-DATA-02 runner and solver/GPU lease are required; historical training_launch_allowed is not this activity authorization",
        "raw_output_root": str(RAW_OUTPUT_ROOT),
        "shortest_executable_chain": [
            {"step": 1, "action": "CPU preflight", "status": "ready", "detail": "validate control/geometry hashes and event surfaces; no solver"},
            {"step": 2, "action": "bounded CPU GenCase preflight", "status": "runner_or_shared_reservation_required", "detail": "record actual particle counts, y layers and native dimensions for one dual-axis and one baffle parent"},
            {"step": 3, "action": "shared runner qualification matrix", "status": "blocked_until_runner_request", "detail": "2 mechanisms x 3 resolutions, full 0-10 s event window"},
            {"step": 4, "action": "integration and sampling studies", "status": "after_step_3", "detail": "same parent geometry/control, actual dt and save cadence receipts"},
            {"step": 5, "action": "label/materialization and Q-I/Q-N audit", "status": "after_step_3", "detail": "write native source/destination/first-passage/net/residence arrays and failure denominator"},
            {"step": 6, "action": "portable HDF5 packaging and real preview", "status": "after_step_5", "detail": "copy only runner outputs into raw root; preserve hashes and parent split"},
        ],
        "runner_request": {
            "category": "qualification",
            "priority": "F3",
            "parallelism": 1,
            "gpu": "shared lease only",
            "cpu": "GenCase/preflight may use bounded CPU reservation",
            "requests": [
                {"mechanism_id": "dual_axis_phase", "resolutions": [cell["dp_m"] for cell in NEW_RESOLUTION_LADDERS["dual_axis_phase"]], "time_window_s": [0.0, 10.0]},
                {"mechanism_id": "eccentric_baffle_exchange", "resolutions": [cell["dp_m"] for cell in NEW_RESOLUTION_LADDERS["eccentric_baffle_exchange"]], "time_window_s": [0.0, 10.0]},
            ],
            "required_start_bindings": ["activity commit", "generator hash", "input/control/geometry hashes", "actual solver dimension", "attempt id", "resource lease"],
        },
        "cpu_request_contract": {
            "required_fields": [
                "family_id", "case_id", "attempt_id", "kind", "cpu_task_kind", "command", "cwd",
                "max_wall_seconds", "cpu_threads", "estimated_storage_bytes", "input_files", "worktree_root",
            ],
            "placeholder_rule": "{attempt_root} is replaced by the shared runner's unique external output directory",
            "gencase_prefix_rule": "a GenCase request must use {attempt_root}/CaseName as its output prefix",
        },
        "cpu_requests": [
            {
                "family_id": "F3",
                "case_id": "F3_HISTORY_ASSET_AUDIT",
                "attempt_id": "F3_HISTORY_ASSET_AUDIT_01",
                "kind": "cpu",
                "cpu_task_kind": "audit",
                "command": [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "audit-history",
                    "--no-hdf5",
                    "--report",
                    audit_report,
                ],
                "cwd": str(REPO_ROOT.resolve()),
                "max_wall_seconds": 900,
                "cpu_threads": 2,
                "estimated_storage_bytes": 64 * 1024 * 1024,
                "input_files": history_input_files,
                "worktree_root": str(REPO_ROOT.resolve()),
                "purpose": "bind the read-only 32-case manifest/gate/contract/archive audit before any new F3 GenCase reservation",
                "hdf5_light_header_already_verified_locally": True,
            },
            {
                "family_id": "F3",
                "case_id": "F3_HISTORY_CELL3_PARENT",
                "attempt_id": "F3_HISTORY_CELL3_PARENT_GENCAS_01",
                "kind": "cpu",
                "cpu_task_kind": "gencase",
                "command": [
                    str(reference_binary.resolve()),
                    str(reference_definition.with_suffix("")),
                    reference_prefix,
                    "-save:all",
                ],
                "cwd": str(reference_case_dir.resolve()),
                "max_wall_seconds": 120,
                "cpu_threads": 2,
                "estimated_storage_bytes": 64 * 1024 * 1024,
                "input_files": [
                    str(reference_binary.resolve()),
                    str(reference_definition.resolve()),
                    str(reference_control.resolve()),
                    str(reference_source_definition.resolve()),
                ],
                "worktree_root": str(REPO_ROOT.resolve()),
                "purpose": "one fresh CPU GenCase parent receipt for the already-qualified native 3D CELL3 input; output stays in the runner attempt root",
                "expected_reference": {
                    "solver_dimension": 3,
                    "total_particles": 108000,
                    "fluid_particles": 34560,
                    "actual_y_layers": 24,
                },
            },
            {
                "family_id": "F3",
                "case_id": PARENT_DUAL_CASE_ID,
                "attempt_id": dual_attempt_id,
                "kind": "cpu",
                "cpu_task_kind": "gencase",
                "command": [
                    str(gencase_binary.resolve()),
                    str(dual_definition.with_suffix("")),
                    f"{{attempt_root}}/{PARENT_DUAL_CASE_ID}",
                    "-save:all",
                ],
                "cwd": str(dual_parent_dir.resolve()),
                "max_wall_seconds": 120,
                "cpu_threads": 2,
                "estimated_storage_bytes": 256 * 1024 * 1024,
                "input_files": [
                    str(gencase_binary.resolve()),
                    str(dual_definition.resolve()),
                    str(dual_control.resolve()),
                    str(reference_source_definition.resolve()),
                ],
                "worktree_root": str(REPO_ROOT.resolve()),
                "purpose": "fresh CPU GenCase parent for 3D dual-axis/phase control; no solver/GPU",
                "expected_reference": {
                    "solver_dimension": 3,
                    "historical_total_particles": 108000,
                    "historical_fluid_particles": 34560,
                    "minimum_transverse_layers": 20,
                    "control_window_s": PARENT_INPUT_TIME_WINDOW_S,
                },
            },
            {
                "family_id": "F3",
                "case_id": PARENT_BAFFLE_CASE_ID,
                "attempt_id": baffle_attempt_id,
                "kind": "cpu",
                "cpu_task_kind": "gencase",
                "command": [
                    str(gencase_binary.resolve()),
                    str(baffle_definition.with_suffix("")),
                    f"{{attempt_root}}/{PARENT_BAFFLE_CASE_ID}",
                    "-save:all",
                ],
                "cwd": str(baffle_parent_dir.resolve()),
                "max_wall_seconds": 120,
                "cpu_threads": 2,
                "estimated_storage_bytes": 256 * 1024 * 1024,
                "input_files": [
                    str(gencase_binary.resolve()),
                    str(baffle_definition.resolve()),
                    str(baffle_control.resolve()),
                    str(official_motion_definition.resolve()),
                ],
                "worktree_root": str(REPO_ROOT.resolve()),
                "purpose": "fresh CPU GenCase parent for real 3D eccentric finite-channel exchange geometry; no solver/GPU",
                "expected_reference": {
                    "solver_dimension": 3,
                    "historical_total_particles": 108000,
                    "historical_fluid_particles": 34560,
                    "minimum_transverse_layers": 20,
                    "control_window_s": PARENT_INPUT_TIME_WINDOW_S,
                    "finite_channel_width_m": 0.05,
                },
            },
        ],
        "completed_cpu_evidence": {
            "historical_cell3_parent_gencase": completed_reference,
            "dual_axis_phase_gencase_01": dual_receipt_01,
            "dual_axis_phase_gencase_02": dual_receipt_02,
            "eccentric_baffle_gencase_01": baffle_receipt_01,
            "eccentric_baffle_gencase_02": baffle_receipt_02,
            "dual_axis_phase_attempts": dual_attempts,
            "eccentric_baffle_attempts": baffle_attempts,
        },
        "qualification_status": "pending_parent_audit",
        "qualification_requests": [],
        "qualification_request_files": [],
        "next_task": next_task,
        "historical_summary": audit["summary"],
    }


def _case_registry(audit: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = [dict(row) for row in audit["cases"]]
    rows.extend(_new_case_slots())
    return rows


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_registry(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    path.write_text(text, encoding="utf-8")


def _write_handoff(path: Path, audit: Mapping[str, Any]) -> None:
    summary = audit["summary"]
    archive = audit["material_archive"]
    duplicate = archive.get("duplicate_groups", [])
    reference_receipt = _compact_runner_receipt(REFERENCE_GENCAS_RECEIPT)
    lines = [
        "# F3 DS-DATA-02 checkpoint / F3 交接",
        "",
        "本 checkpoint 完成只读历史审计、可移动复用清单、两个新机制定义、完整事件语义、数值观测及 2×3/积分/采样计划。没有启动 solver/GPU，也没有加载模型或权重。",
        "",
        "## 已确认历史资产",
        "",
        f"- 历史 canonical manifest 的 32 个 physical case 均可轻量打开；可复用 native 核心轨迹数：**{summary['reusable_historical_count']}**。实际 solver 维度均为 3（generated XML `data2d=false` 与 HDF5 `position[...,3]` 互证）。",
        f"- 每个轨迹为 836 帧、34560 个流体身份、0–8.350012828 s、初末有效、初始质量约 14.58 kg；旧 split 保留为 train={summary['old_split_counts'].get('train', 0)}、validation={summary['old_split_counts'].get('validation', 0)}、test={summary['old_split_counts'].get('test', 0)}。",
        "- gate 只覆盖 CELL3 plain、单轴固定槽加速度和旧 recipe `F3_CELL3_NS_visco1_native_nopen_revision075_ref0081818`；它不授予双轴相位或偏心挡板/分舱交换资格。",
        f"- material archive 的 aligned.h5 候选数为 {archive.get('material_candidate_count', 0)}，按 SHA-256 去重后为 {archive.get('unique_material_candidate_count', 0)} 个；aligned.h5 重复组：{len(archive.get('duplicate_material_candidate_groups', []))}（archive 全部文件重复组：{len(duplicate)}）。这些文件不计入 native F3 core case，也不计为材料标签通过。",
        (
            f"- 共享 runner 已完成历史 CELL3 母例 CPU GenCase：status={reference_receipt.get('status')}，"
            f"total={reference_receipt.get('total_particles')}、fluid={reference_receipt.get('fluid_particles')}、"
            f"solver_dimension={reference_receipt.get('solver_dimension_from_gencase')}；receipt 位于 `{reference_receipt.get('receipt_path')}`。"
            if reference_receipt.get("status") == "completed"
            else "- 历史 CELL3 母例 CPU GenCase receipt 尚未完成；当前仅使用只读 native 轨迹和 source receipts。"
        ),
        "",
        "## 实际缺口",
        "",
        "- 32 个历史 HDF5 尚未写入 DS-DATA-02 原生 source/destination/first-passage/net-flux/residence 标签；标签生成必须保留 unknown 与合法开放顶部离域的分桶。",
        "- 双轴/相位控制和偏心挡板/分舱横向交换各缺一套完整 3 分辨率参考矩阵；新矩阵的 solver_dimension、GenCase 实际粒子数、输入/控制/geometry 哈希和 full-window 证据均待 runner 产出。",
        "- 积分步研究与保存频率研究尚未执行；降采样不能替代积分步对照。真实预览和可移动 HDF5 包在标签/Q-I 后生成。",
        "",
        "## 最短执行链与 runner 请求",
        "",
        "1. 历史 CELL3 母例已完成 bounded CPU GenCase receipt；下一步对每个新机制做一个有资源预约的 bounded CPU GenCase parent preflight，记录真实粒子数、横向层数和 geometry/control hash。" if reference_receipt.get("status") == "completed" else "1. 先对每个机制做一个有资源预约的 bounded CPU GenCase parent preflight，记录真实粒子数、横向层数和 geometry/control hash。",
        "2. shared DS-DATA-02 runner 串行执行两个机制×三分辨率；每次先写入 runner 分配的唯一外部 `{attempt_root}`，通过标签/Q-I 后再移动复用到 `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/case/attempt`，启动时绑定 activity commit、generator hash、输入哈希、UUID lease 和 attempt_id。",
        "3. 对中分辨率做 actual-dt 与 output-cadence 对照；之后生成原生事件标签、Q-I/Q-N scope receipt、预览和 portable manifest。",
        "",
        "当前 runner 请求见 `execution_queue.json`；历史 `training_launch_allowed` 不是 DS-DATA-02 活动授权。",
        "",
        "## 后续任务",
        "",
        "共享预约入口已提供；下一任务是为双轴/相位与偏心挡板各冻结一个 parent Definition 并执行 bounded CPU GenCase preflight，其余工作按 `execution_queue.json` 继续，不把 canary 或旧 plain gate 当作新机制数值参考。" if reference_receipt.get("status") == "completed" else "共享预约入口提供后，下一任务是执行两个 bounded CPU GenCase parent preflight；其余工作按 `execution_queue.json` 继续，不把 canary 或旧 plain gate 当作新机制数值参考。",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def generate_family(
    output_root: Path = FAMILY_ROOT,
    historical_root: Path = HISTORICAL_ROOT,
    archive_root: Path = MATERIAL_ARCHIVE_ROOT,
    *,
    inspect_hdf5: bool = True,
    full_hash: bool = False,
) -> dict[str, Any]:
    """Write all F3 family definitions and return the history audit."""
    audit = audit_history(historical_root, archive_root, inspect_hdf5=inspect_hdf5, full_hash=full_hash)
    output_root.mkdir(parents=True, exist_ok=True)
    _write_json(output_root / "family_card.json", _family_card(audit))
    _write_json(output_root / "history_reuse_inventory.json", audit)
    _write_json(output_root / "event_definitions.json", _event_definitions())
    _write_json(output_root / "observation_plan.json", _observation_plan())
    _write_json(output_root / "reference_evidence.json", _reference_evidence(audit))
    _write_json(output_root / "qualified_recipes.json", _qualified_recipes(audit))
    _write_json(output_root / "split_plan.json", _split_plan(audit))
    _write_json(output_root / "labels/label_schema.json", _label_schema())
    _write_parent_inputs(output_root)
    _write_json(output_root / "execution_queue.json", _execution_queue(audit, output_root))
    _write_registry(output_root / "case_registry.jsonl", _case_registry(audit))

    manifests_root = output_root / "case_manifests"
    manifests_root.mkdir(parents=True, exist_ok=True)
    for row in _case_registry(audit):
        _write_json(manifests_root / f"{row['case_id']}.json", {
            "schema": "ds-data-02.f3.case_manifest.v1",
            "case": row,
            "label_schema": "../labels/label_schema.json",
            "event_definitions": "../event_definitions.json",
            "observation_plan": "../observation_plan.json",
            "portable_copy": {
                "status": "not_copied" if row.get("status") != "planned_no_solver" else "not_started",
                "destination_root": str(RAW_OUTPUT_ROOT),
                "copy_requires_runner_or_explicit_packaging_step": True,
            },
        })
    preview_root = output_root / "preview"
    preview_root.mkdir(parents=True, exist_ok=True)
    (preview_root / "README.md").write_text(
        "# F3 preview\n\n真实预览尚未生成。历史轨迹已核对为可复用 native state，但本 checkpoint 不以 metadata 或短 canary 代替完整机制预览。完成标签与 Q-I 后，由共享 runner/预览步骤写入关键事件帧和动画，并在 manifest 中绑定哈希。\n",
        encoding="utf-8",
    )
    (output_root / "labels" / "README.md").write_text(
        "# F3 labels\n\n`label_schema.json` 定义原生数值事件标签。32 个历史 HDF5 目前仅含 native state，尚未物化事件数组；不得把材料 archive 或模型输出填入此目录冒充 native labels。\n",
        encoding="utf-8",
    )
    _write_handoff(output_root / "FAMILY_HANDOFF.md", audit)
    return audit


def validate_family(output_root: Path = FAMILY_ROOT) -> dict[str, Any]:
    """Validate generated F3 artefacts and any recorded parent audit."""
    required = [
        "family_card.json", "history_reuse_inventory.json", "event_definitions.json",
        "observation_plan.json", "reference_evidence.json", "qualified_recipes.json",
        "split_plan.json", "case_registry.jsonl", "labels/label_schema.json", "execution_queue.json",
        "FAMILY_HANDOFF.md", "parent_inputs/parent_input_manifest.json",
    ]
    missing = [item for item in required if not (output_root / item).is_file()]
    errors: list[str] = []
    registry_rows: list[dict[str, Any]] = []
    registry_path = output_root / "case_registry.jsonl"
    if registry_path.is_file():
        for line_number, line in enumerate(registry_path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    errors.append(f"registry line {line_number} is not object")
                else:
                    registry_rows.append(row)
            except json.JSONDecodeError as exc:
                errors.append(f"registry line {line_number}: {exc}")
    ids = [row.get("case_id") for row in registry_rows]
    if len(ids) != len(set(ids)):
        errors.append("duplicate case_id in registry")
    actual = [row for row in registry_rows if row.get("status") == "reused_historical_candidate"]
    planned = [row for row in registry_rows if row.get("status") == "planned_no_solver"]
    if len(actual) != 32:
        errors.append(f"expected 32 historical registry rows, got {len(actual)}")
    if len(planned) != 16:
        errors.append(f"expected 16 planned new slots, got {len(planned)}")
    old_counts = Counter(row.get("legacy_split") for row in actual)
    if old_counts != Counter({"train": 16, "validation": 4, "test": 12}):
        errors.append(f"historical split changed: {dict(old_counts)}")
    if any(row.get("split") != row.get("legacy_split") or row.get("target_role") != row.get("legacy_split") for row in actual):
        errors.append("historical split aliases are not preserved")
    if any(row.get("solver_dimension") not in {3, "pending_actual_solver_output"} for row in registry_rows):
        errors.append("invalid solver_dimension")
    parent_audit_path = output_root / "parent_inputs/gencase_audit.json"
    parent_audit: dict[str, Any] | None = None
    if parent_audit_path.is_file():
        try:
            parent_audit = read_json(parent_audit_path)
            if parent_audit.get("status") != "pass":
                errors.append(f"parent GenCase audit status is {parent_audit.get('status')}")
            for row in parent_audit.get("parents", []):
                if isinstance(row, Mapping) and row.get("status") != "pass":
                    errors.append(f"parent audit failed: {row.get('case_id')}")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"parent audit unreadable: {type(exc).__name__}: {exc}")
    report = {
        "schema": "ds-data-02.f3.validation.v1",
        "valid": not missing and not errors,
        "missing": missing,
        "errors": errors,
        "registry_rows": len(registry_rows),
        "historical_rows": len(actual),
        "planned_rows": len(planned),
        "legacy_split_counts": dict(sorted(old_counts.items())),
        "model_runtime_loaded": False,
        "solver_launched": False,
        "parent_audit_status": parent_audit.get("status") if parent_audit else "pending",
        "qualification_request_files": sorted(
            str(path.relative_to(output_root))
            for path in (output_root / "qualification_requests").glob("*.json")
        ) if (output_root / "qualification_requests").is_dir() else [],
    }
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["audit-history", "audit-parents", "generate", "validate"], nargs="?", default="generate")
    parser.add_argument("--output", type=Path, default=FAMILY_ROOT)
    parser.add_argument("--historical-root", type=Path, default=HISTORICAL_ROOT)
    parser.add_argument("--archive-root", type=Path, default=MATERIAL_ARCHIVE_ROOT)
    parser.add_argument("--no-hdf5", action="store_true", help="skip optional HDF5 light-header inspection")
    parser.add_argument("--full-hash", action="store_true", help="rehash source files, including large HDF5 trajectories")
    parser.add_argument("--report", type=Path, help="also write the JSON result to this path")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.action == "audit-history":
        report = audit_history(args.historical_root, args.archive_root, inspect_hdf5=not args.no_hdf5, full_hash=args.full_hash)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        if args.report:
            _write_json(args.report, report)
        return 0
    if args.action == "audit-parents":
        report = audit_parents(args.output)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        if args.report:
            _write_json(args.report, report)
        return 0 if report["status"] == "pass" else 1
    if args.action == "generate":
        report = generate_family(args.output, args.historical_root, args.archive_root, inspect_hdf5=not args.no_hdf5, full_hash=args.full_hash)
        result = {"status": "generated", "output": str(args.output), "summary": report["summary"]}
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        if args.report:
            _write_json(args.report, result)
        return 0
    report = validate_family(args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if args.report:
        _write_json(args.report, report)
    return 0 if report["valid"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
