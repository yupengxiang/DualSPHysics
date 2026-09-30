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
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA = "ds-data-02.f3.family.v1"
GENERATOR_VERSION = "ds_data02_f3.v1"
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


def _execution_queue(audit: Mapping[str, Any]) -> dict[str, Any]:
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
    next_task = (
        "write/freeze the two new mechanism parent definitions, then submit one bounded CPU GenCase request per mechanism"
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
        ],
        "completed_cpu_evidence": {
            "historical_cell3_parent_gencase": completed_reference,
        },
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
    _write_json(output_root / "execution_queue.json", _execution_queue(audit))
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
    """Validate generated F3 artefacts without reading any solver output."""
    required = [
        "family_card.json", "history_reuse_inventory.json", "event_definitions.json",
        "observation_plan.json", "reference_evidence.json", "qualified_recipes.json",
        "split_plan.json", "case_registry.jsonl", "labels/label_schema.json", "execution_queue.json",
        "FAMILY_HANDOFF.md",
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
    }
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["audit-history", "generate", "validate"], nargs="?", default="generate")
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
