#!/usr/bin/env python3
"""Read-only L2-R F2 audit entry point.

This module audits the F2 assets that already exist in the repository.  It does
not run GenCase, DualSPHysics, PartVTK, or any GPU job.  The audit is purposely
stricter than the historical W06/R3 reports:

* a moving cup needs both a declared motion file and a finite body-space cup
  geometry plus a per-frame world-from-body transform;
* an angle trace without that transform leaves moving geometry ``unknown``;
* a zero-angle prefix is not promoted to a dedicated static-cup hold check;
* two same-solver backgrounds and an old canary are not independent reference
  evidence.

The script is an independent research/audit entrance.  It never updates the
L2-R scheduler state, qualification ledger, or D0/E0 artifacts.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from typing import Any, Iterable

import h5py
import numpy as np


LAB = Path(__file__).resolve().parents[1]
EXPECTED_BACKGROUNDS = ("slow_center", "offset_partial")
SCHEMA = "l2r.f2r.audit.v1"


@dataclass(frozen=True)
class AssetSpec:
    asset_id: str
    background: str
    hdf5: Path
    definition: Path
    evidence_class: str
    mechanism: str
    static_hold: bool = False
    new_f2r_evidence: bool = False


def _rel(path: Path, lab: Path = LAB) -> str:
    """Return a stable repository-relative path when possible."""

    try:
        return path.resolve().relative_to(lab.resolve()).as_posix()
    except ValueError:
        return str(path)


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _finite_float(value: str | None) -> float | None:
    try:
        number = float(value) if value is not None else math.nan
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _attr_number(node: ET.Element, key: str) -> float | None:
    return _finite_float(node.attrib.get(key))


def _tag(node: ET.Element) -> str:
    return node.tag.rsplit("}", 1)[-1]


def _box_faces(node: ET.Element) -> list[str]:
    text = "".join(node.itertext()).strip().lower()
    return sorted(part.strip() for part in text.split("|") if part.strip())


def _is_finite_box(box: dict[str, Any]) -> bool:
    return (
        all(math.isfinite(float(value)) for value in box["point"] + box["size"])
        and all(float(value) > 0 for value in box["size"])
    )


def _motion_path_from_definition(definition: Path, name: str | None) -> Path | None:
    if not name:
        return None
    candidate = Path(name)
    return candidate if candidate.is_absolute() else definition.parent / candidate


def _parse_motion_file(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {
            "exists": False,
            "path": None,
            "rows": 0,
            "status": "unknown",
            "reason": "no motion file is declared",
        }
    if not path.is_file():
        return {
            "exists": False,
            "path": str(path),
            "rows": 0,
            "status": "blocked",
            "reason": "declared motion file is missing",
        }
    rows: list[tuple[float, float]] = []
    malformed = 0
    for raw in path.read_text(errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = [field for field in re.split(r"[;,\s]+", line) if field]
        if len(fields) < 2:
            malformed += 1
            continue
        try:
            rows.append((float(fields[0]), float(fields[1])))
        except ValueError:
            malformed += 1
    if not rows:
        return {
            "exists": True,
            "path": str(path),
            "sha256": _sha256(path),
            "rows": 0,
            "malformed_rows": malformed,
            "status": "blocked",
            "reason": "motion file has no numeric time/angle rows",
        }
    values = np.asarray(rows, dtype=float)
    order = np.argsort(values[:, 0], kind="stable")
    values = values[order]
    monotonic = bool(np.all(np.diff(values[:, 0]) > 0))
    finite = bool(np.isfinite(values).all())
    nonzero = bool(np.max(np.abs(values[:, 1] - values[0, 1])) > 1e-9)
    status = "checked" if monotonic and finite else "blocked"
    return {
        "exists": True,
        "path": str(path),
        "sha256": _sha256(path),
        "rows": int(len(values)),
        "malformed_rows": malformed,
        "time_start_s": float(values[0, 0]),
        "time_end_s": float(values[-1, 0]),
        "angle_min_degrees": float(np.min(values[:, 1])),
        "angle_max_degrees": float(np.max(values[:, 1])),
        "nonzero_motion": nonzero,
        "strictly_increasing_time": monotonic,
        "finite": finite,
        "status": status,
        "reason": None if status == "checked" else "motion time/angle series is not finite and strictly increasing",
        "_samples": values,
    }


def _parse_definition(path: Path) -> dict[str, Any]:
    """Extract finite source geometry and the declared rigid motion contract."""

    result: dict[str, Any] = {
        "path": str(path),
        "exists": path.is_file(),
        "sha256": _sha256(path),
        "motion_declared": False,
        "motion_file": None,
        "drawboxes": [],
        "cup_components": [],
        "capture_components": [],
        "spill_components": [],
        "geometry_status": "unknown",
        "errors": [],
    }
    if not path.is_file():
        result["errors"].append("source_definition_missing")
        return result
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        result["errors"].append(f"source_definition_unreadable:{exc}")
        return result

    motion_nodes = root.findall(".//mvrotfile")
    result["motion_declared"] = bool(motion_nodes or root.findall(".//motion"))
    if motion_nodes:
        file_node = motion_nodes[0].find("file")
        if file_node is not None:
            result["motion_file"] = file_node.attrib.get("name")

    current_kind: str | None = None
    current_mk: int | None = None
    commands = root.find(".//geometry/commands/mainlist")
    if commands is None:
        result["errors"].append("geometry_mainlist_missing")
    else:
        for node in commands:
            name = _tag(node)
            if name == "setmkbound":
                current_kind = "bound"
                try:
                    current_mk = int(node.attrib["mk"])
                except (KeyError, ValueError):
                    current_mk = None
            elif name == "setmkfluid":
                current_kind = "fluid"
                try:
                    current_mk = int(node.attrib["mk"])
                except (KeyError, ValueError):
                    current_mk = None
            elif name == "setmkvoid":
                current_kind = "void"
                current_mk = None
            elif name == "drawbox":
                point_node = node.find("point")
                size_node = node.find("size")
                if point_node is None or size_node is None:
                    result["errors"].append("drawbox_missing_point_or_size")
                    continue
                point = [_attr_number(point_node, axis) for axis in "xyz"]
                size = [_attr_number(size_node, axis) for axis in "xyz"]
                fill_node = node.find("boxfill")
                box = {
                    "kind": current_kind,
                    "mk": current_mk,
                    "faces": _box_faces(fill_node if fill_node is not None else node),
                    "point": point,
                    "size": size,
                }
                box["finite"] = all(value is not None for value in point + size) and _is_finite_box({
                    "point": [float(value) for value in point if value is not None],
                    "size": [float(value) for value in size if value is not None],
                }) if all(value is not None for value in point + size) else False
                result["drawboxes"].append(box)

    # The W06/R3 cup contract is explicit: mk=0 is the finite cup made of all
    # faces except the mouth/top.  mk=1 is the fixed receiver and mk=2 is the
    # fixed tray.  This role detection is deliberately limited to finite XML
    # drawboxes; no free-space AABB is accepted as a substitute.
    for index, box in enumerate(result["drawboxes"]):
        faces = set(box["faces"])
        if box["kind"] != "bound" or not box["finite"]:
            continue
        annotated = dict(box)
        annotated["drawbox_index"] = index
        if box["mk"] == 0 and {"bottom", "left", "right", "front", "back"}.issubset(faces):
            result["cup_components"].append(annotated)
        if box["mk"] == 1 and {"bottom", "left", "right", "front", "back"}.issubset(faces):
            result["capture_components"].append(annotated)
        if box["mk"] == 2 and faces == {"bottom"}:
            result["spill_components"].append(annotated)

    if result["errors"]:
        result["geometry_status"] = "blocked"
    elif result["cup_components"] and result["capture_components"] and result["spill_components"]:
        result["geometry_status"] = "checked"
    elif result["cup_components"] or result["capture_components"]:
        result["geometry_status"] = "unknown"
    else:
        result["geometry_status"] = "blocked"
    return result


def _strip_samples(payload: Any) -> Any:
    """Remove internal NumPy samples before serialising a report."""

    if isinstance(payload, dict):
        return {key: _strip_samples(value) for key, value in payload.items() if key != "_samples"}
    if isinstance(payload, list):
        return [_strip_samples(value) for value in payload]
    return payload


def _h5_attr(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, np.generic):
        return value.item()
    return value


def _dataset_finite_counts(array: np.ndarray, valid: np.ndarray) -> tuple[int, int]:
    if array.ndim == valid.ndim + 1:
        finite = np.isfinite(array).all(axis=-1)
    else:
        finite = np.isfinite(array)
    return int((valid & ~finite).sum()), int((~valid & ~finite).sum())


def _trajectory_summary(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(path),
        "exists": path.is_file(),
        "sha256": _sha256(path),
        "status": "unknown",
        "errors": [],
    }
    if not path.is_file():
        result["errors"].append("hdf5_missing")
        return result
    try:
        with h5py.File(path, "r") as h5:
            result["attrs"] = {str(key): _h5_attr(value) for key, value in h5.attrs.items()}
            required = ("time", "position", "velocity", "mass", "valid", "type")
            missing = [name for name in required if name not in h5]
            if missing:
                result["errors"].append(f"missing_datasets:{','.join(missing)}")
                return result
            time = np.asarray(h5["time"][:], dtype=float)
            position = np.asarray(h5["position"][:])
            velocity = np.asarray(h5["velocity"][:])
            mass = np.asarray(h5["mass"][:])
            valid = np.asarray(h5["valid"][:], dtype=bool)
            particle_type = np.asarray(h5["type"][:])
            if valid.ndim != 2 or position.ndim != 3 or position.shape[-1] != 3:
                result["errors"].append("unexpected_trajectory_shapes")
                return result
            if any(array.shape[:2] != valid.shape for array in (position, velocity, mass, particle_type)):
                result["errors"].append("trajectory_shape_mismatch")
                return result
            if len(time) != valid.shape[0]:
                result["errors"].append("time_frame_mismatch")
                return result
            initial_fluid = valid[0] & (particle_type[0] == 3)
            active_nonfinite = {}
            inactive_nonfinite = {}
            for name, array in (("position", position), ("velocity", velocity), ("mass", mass)):
                active, inactive = _dataset_finite_counts(array, valid)
                active_nonfinite[name] = active
                inactive_nonfinite[name] = inactive
            mass_values = mass[0, initial_fluid]
            positive_mass = bool(len(mass_values) and np.isfinite(mass_values).all() and (mass_values > 0).all())
            initial_mass = float(np.sum(mass_values)) if positive_mass else None
            final_valid_initial = valid[-1] & initial_fluid
            final_mass = float(np.sum(mass[-1, final_valid_initial])) if final_valid_initial.any() else 0.0
            births_after_initial = valid[1:] & ~initial_fluid[None, :]
            transition_count = int(np.abs(np.diff(valid.astype(np.int8), axis=0)).sum()) if len(valid) > 1 else 0
            result.update({
                "frame_count": int(valid.shape[0]),
                "particle_count": int(valid.shape[1]),
                "time_start_s": float(time[0]) if len(time) else None,
                "time_end_s": float(time[-1]) if len(time) else None,
                "time_strictly_increasing": bool(len(time) < 2 or np.all(np.diff(time) > 0)),
                "active_entries_scanned": int(valid.sum()),
                "initial_fluid_particles": int(initial_fluid.sum()),
                "final_initial_identity_count": int(final_valid_initial.sum()),
                "missing_initial_identities_at_final": int((initial_fluid & ~valid[-1]).sum()),
                "identities_introduced_after_initial": int(births_after_initial.any(axis=0).sum()),
                "valid_transition_count": transition_count,
                "active_nonfinite": active_nonfinite,
                "inactive_nonfinite_padding": inactive_nonfinite,
                "initial_mass_kg": initial_mass,
                "final_mass_kg_over_initial_identities": final_mass,
                "mass_retention_fraction": final_mass / initial_mass if initial_mass else None,
                "positive_initial_mass": positive_mass,
            })
            if not result["time_strictly_increasing"]:
                result["errors"].append("time_not_strictly_increasing")
            for name, count in active_nonfinite.items():
                if count:
                    result["errors"].append(f"active_nonfinite:{name}")
            if not positive_mass:
                result["errors"].append("initial_mass_not_finite_positive")
            result["status"] = "checked" if not result["errors"] else "blocked"
    except (OSError, ValueError, KeyError) as exc:
        result["errors"].append(f"hdf5_unreadable:{exc}")
        result["status"] = "blocked"
    return result


def _matrix_is_finite_and_rigid(transform: np.ndarray) -> bool:
    if transform.shape[-2:] != (4, 4) or not np.isfinite(transform).all():
        return False
    homogeneous = np.allclose(transform[:, 3, :], np.asarray([0.0, 0.0, 0.0, 1.0]), atol=1e-5)
    rotation = transform[:, :3, :3]
    orthogonal = np.allclose(
        np.matmul(np.transpose(rotation, (0, 2, 1)), rotation),
        np.broadcast_to(np.eye(3), (len(rotation), 3, 3)),
        atol=2e-3,
    )
    determinant = np.linalg.det(rotation)
    return bool(homogeneous and orthogonal and np.allclose(determinant, 1.0, atol=2e-3))


def _control_summary(hdf5: Path, definition: dict[str, Any]) -> dict[str, Any]:
    """Audit prescribed motion and classify moving geometry conservatively."""

    result: dict[str, Any] = {
        "motion_status": "unknown",
        "moving_geometry_status": "unknown",
        "static_prefix": {"present": False, "duration_s": 0.0},
        "control_angle_present": False,
        "world_from_body_present": False,
        "replayable_from_declared_file": False,
        "errors": [],
    }
    source_motion = _motion_path_from_definition(
        Path(definition["path"]), definition.get("motion_file")
    ) if definition.get("motion_file") else None
    motion = _parse_motion_file(source_motion)
    result["declared_motion"] = bool(definition.get("motion_declared"))
    result["declared_motion_file"] = motion
    if not hdf5.is_file():
        result["errors"].append("hdf5_missing")
        return result
    try:
        with h5py.File(hdf5, "r") as h5:
            time = np.asarray(h5["time"][:], dtype=float) if "time" in h5 else np.asarray([])
            control = h5.get("control")
            angle = np.asarray(control["cup_angle_degrees"][:], dtype=float) if control is not None and "cup_angle_degrees" in control else None
            transform = np.asarray(control["cup_world_from_body"][:], dtype=float) if control is not None and "cup_world_from_body" in control else None
            result["control_angle_present"] = angle is not None
            result["world_from_body_present"] = transform is not None
            if angle is not None:
                result["control_angle_finite"] = bool(np.isfinite(angle).all())
                result["control_angle_range_degrees"] = [float(np.min(angle)), float(np.max(angle))] if len(angle) else None
                result["control_nonzero_motion"] = bool(len(angle) and np.max(np.abs(angle - angle[0])) > 1e-9)
                zero = np.abs(angle - angle[0]) <= 1e-8
                if zero.any():
                    prefix = 0
                    while prefix < len(zero) and bool(zero[prefix]):
                        prefix += 1
                    if prefix:
                        end_time = float(time[prefix - 1]) if len(time) >= prefix else 0.0
                        result["static_prefix"] = {"present": True, "duration_s": end_time, "frames": prefix}
            transform_valid = transform is not None and _matrix_is_finite_and_rigid(transform)
            result["world_from_body_finite_rigid"] = bool(transform_valid)
            if transform is not None and len(transform):
                delta_translation = np.linalg.norm(transform[:, :3, 3] - transform[0, :3, 3], axis=1)
                delta_rotation = np.linalg.norm(transform[:, :3, :3] - transform[0, :3, :3], axis=(1, 2))
                result["world_from_body_max_translation_m"] = float(np.max(delta_translation))
                result["world_from_body_max_rotation_matrix_delta"] = float(np.max(delta_rotation))
                result["transform_nonzero_motion"] = bool(np.max(delta_translation + delta_rotation) > 1e-8)
            else:
                result["transform_nonzero_motion"] = False
            if angle is not None and motion.get("_samples") is not None and len(time) == len(angle):
                samples = motion["_samples"]
                if len(samples) >= 2 and np.all(np.diff(samples[:, 0]) > 0):
                    expected = np.interp(time, samples[:, 0], samples[:, 1])
                    error = np.abs(expected - angle)
                    result["motion_file_angle_max_abs_error_degrees"] = float(np.max(error))
                    result["motion_file_angle_p95_abs_error_degrees"] = float(np.quantile(error, 0.95))
                    result["replayable_from_declared_file"] = bool(np.isfinite(error).all() and np.max(error) <= 1e-5)
            if definition.get("motion_declared"):
                if motion["status"] != "checked":
                    result["errors"].append("declared_motion_file_not_checked")
                if angle is None or not result.get("control_angle_finite", False):
                    result["errors"].append("control_angle_missing_or_nonfinite")
                if not result.get("replayable_from_declared_file", False):
                    result["errors"].append("motion_file_and_control_do_not_form_replayable_pair")
                result["motion_status"] = "checked" if not result["errors"] else "blocked"
                if not transform_valid:
                    # An angle trace is not a world-space moving geometry
                    # proof.  Preserve unknown rather than silently using an
                    # AABB or assuming the old canary's cup path.
                    result["moving_geometry_status"] = "unknown"
                    result["moving_geometry_reason"] = "declared moving cup lacks a finite rigid world_from_body transform"
                elif definition.get("geometry_status") != "checked":
                    result["moving_geometry_status"] = "blocked"
                    result["moving_geometry_reason"] = "moving geometry source is not a complete finite cup/receiver/tray contract"
                elif not result.get("transform_nonzero_motion", False):
                    result["moving_geometry_status"] = "blocked"
                    result["moving_geometry_reason"] = "declared motion has no nonzero world-space transform"
                else:
                    result["moving_geometry_status"] = "checked"
            else:
                result["motion_status"] = "static_candidate"
                result["moving_geometry_status"] = "not_applicable"
    except (OSError, KeyError, ValueError) as exc:
        result["errors"].append(f"control_unreadable:{exc}")
        result["motion_status"] = "blocked"
        result["moving_geometry_status"] = "unknown"
    return result


def _capture_geometry_summary(definition: dict[str, Any]) -> dict[str, Any]:
    if definition.get("geometry_status") == "checked":
        return {
            "status": "checked",
            "method": "finite_source_drawbox_components",
            "aabb_fallback_used": False,
            "cup_component_count": len(definition["cup_components"]),
            "capture_component_count": len(definition["capture_components"]),
            "spill_component_count": len(definition["spill_components"]),
        }
    return {
        "status": "blocked" if definition.get("geometry_status") == "blocked" else "unknown",
        "method": "finite_source_drawbox_components",
        "aabb_fallback_used": False,
        "reason": "capture geometry is not a complete finite source contract",
        "cup_component_count": len(definition.get("cup_components", [])),
        "capture_component_count": len(definition.get("capture_components", [])),
        "spill_component_count": len(definition.get("spill_components", [])),
    }


def default_asset_specs(lab: Path = LAB) -> list[AssetSpec]:
    """Return read-only F2 assets, explicitly labelled by evidence class."""

    return [
        AssetSpec(
            "L2_C1_F2_rotation_center_nominal",
            "slow_center",
            lab / "campaigns/l2-multifamily/c1-canary/data/L2_C1_F2_rotation_center_nominal.h5",
            lab / "campaigns/v0.1-candidate/cases/w06/W06_standard_slow_center_Def.xml",
            "legacy_canary",
            "real-rotating-cup-centered-catch",
        ),
        AssetSpec(
            "R3_F2_slow_center_massmatched_fine",
            "slow_center",
            lab / "campaigns/v0.1-candidate/data/r3-g2-f2/R3_F2_slow_center_massmatched_fine.h5",
            lab / "campaigns/v0.1-candidate/cases/r3-g2-f2/R3_F2_slow_center_massmatched_fine_Def.xml",
            "legacy_same_solver_resolution_matrix",
            "rotating-cup-pour-resolution",
        ),
        AssetSpec(
            "R3_F2_offset_partial_massmatched_fine",
            "offset_partial",
            lab / "campaigns/v0.1-candidate/data/r3-g2-f2/R3_F2_offset_partial_massmatched_fine.h5",
            lab / "campaigns/v0.1-candidate/cases/r3-g2-f2/R3_F2_offset_partial_massmatched_fine_Def.xml",
            "legacy_same_solver_resolution_matrix",
            "rotating-cup-pour-resolution",
        ),
        AssetSpec(
            "F2_airborne_slug_centered",
            "legacy_centered",
            lab / "campaigns/v0.1-candidate/data/F2_airborne_slug_centered.h5",
            lab / "cases/F2/F2_airborne_slug_centered/F2_airborne_slug_centered_Def.xml",
            "legacy_mechanism_probe",
            "transfer-catch-spill",
        ),
        AssetSpec(
            "F2_airborne_slug_offset",
            "legacy_offset",
            lab / "campaigns/v0.1-candidate/data/F2_airborne_slug_offset.h5",
            lab / "cases/F2/F2_airborne_slug_offset/F2_airborne_slug_offset_Def.xml",
            "legacy_mechanism_probe",
            "offset-transfer-partial-capture",
        ),
        AssetSpec(
            "F2_two_source_layers",
            "legacy_two_source",
            lab / "campaigns/v0.1-candidate/data/F2_two_source_layers.h5",
            lab / "cases/F2/F2_two_source_layers/F2_two_source_layers_Def.xml",
            "legacy_mechanism_probe",
            "source-layer-destination-allocation",
        ),
    ]


def audit_asset(spec: AssetSpec, lab: Path = LAB) -> dict[str, Any]:
    definition = _parse_definition(spec.definition)
    trajectory = _trajectory_summary(spec.hdf5)
    control = _control_summary(spec.hdf5, definition)
    capture = _capture_geometry_summary(definition)
    status = "checked" if trajectory.get("status") == "checked" else "blocked"
    if control.get("moving_geometry_status") in {"unknown", "blocked"} and definition.get("motion_declared"):
        status = "blocked"
    return {
        "asset_id": spec.asset_id,
        "background": spec.background,
        "mechanism": spec.mechanism,
        "evidence_class": spec.evidence_class,
        "eligible_as_new_f2r_evidence": bool(spec.new_f2r_evidence),
        "promotion_policy": "legacy/canary assets are never promoted by this audit",
        "paths": {
            "hdf5": _rel(spec.hdf5, lab),
            "definition": _rel(spec.definition, lab),
        },
        "trajectory": _strip_samples(trajectory),
        "definition": _strip_samples(definition),
        "motion": _strip_samples(control),
        "capture_geometry": capture,
        "audit_status": status,
    }


def _static_cup_check(assets: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = []
    preludes = []
    for asset in assets:
        motion = asset["motion"]
        if motion.get("static_prefix", {}).get("present"):
            preludes.append({
                "asset_id": asset["asset_id"],
                "background": asset["background"],
                "duration_s": motion["static_prefix"]["duration_s"],
                "role": "moving-case-zero-motion-prefix_not_static_evidence",
            })
        if (
            asset.get("evidence_class") == "new_f2r_static_hold"
            and asset["definition"].get("motion_declared") is False
            and asset["capture_geometry"].get("status") == "checked"
            and asset["trajectory"].get("status") == "checked"
        ):
            candidates.append(asset["asset_id"])
    if candidates:
        return {
            "status": "checked",
            "dedicated_static_hold_assets": candidates,
            "zero_motion_preludes_not_counted": preludes,
            "reason": None,
        }
    return {
        "status": "blocked",
        "dedicated_static_hold_assets": [],
        "zero_motion_preludes_not_counted": preludes,
        "reason": "no dedicated zero-drive static cup hold with finite cup/capture/tray geometry exists in the current assets",
    }


def _moving_cup_check(assets: list[dict[str, Any]]) -> dict[str, Any]:
    per_background: dict[str, Any] = {}
    blockers: list[str] = []
    for background in EXPECTED_BACKGROUNDS:
        selected = [asset for asset in assets if asset["background"] == background]
        geometry_checked = [
            asset["asset_id"] for asset in selected
            if asset["motion"].get("moving_geometry_status") == "checked"
        ]
        unknown = [
            asset["asset_id"] for asset in selected
            if asset["motion"].get("moving_geometry_status") == "unknown"
        ]
        per_background[background] = {
            "geometry_checked_assets": geometry_checked,
            "geometry_unknown_assets": unknown,
            "legacy_assets_not_promoted": [asset["asset_id"] for asset in selected],
            "status": "checked" if geometry_checked else ("unknown" if unknown else "blocked"),
        }
        if not geometry_checked:
            blockers.append(f"{background}: no finite replayable moving-cup geometry")
        elif not any(asset["eligible_as_new_f2r_evidence"] for asset in selected):
            blockers.append(f"{background}: moving geometry is legacy-only, not new F2R evidence")
    return {
        "status": "blocked" if blockers else "checked",
        "per_background": per_background,
        "blockers": blockers,
        "strict_geometry_policy": "unknown/blocked; never infer moving geometry from angle or AABB alone",
    }


def _reference_gate(assets: list[dict[str, Any]], lab: Path) -> dict[str, Any]:
    """Require two F2 background-specific independent anchors.

    The current repository has no accepted external/analytical F2 reference
    metadata.  Same-solver HDF5s, old canaries, and F3 official sloshing data
    are listed as blockers rather than silently counted.
    """

    background_evidence: dict[str, Any] = {}
    blockers: list[str] = []
    for background in EXPECTED_BACKGROUNDS:
        selected = [asset for asset in assets if asset["background"] == background]
        same_solver = [asset["asset_id"] for asset in selected if "same_solver" in asset["evidence_class"]]
        canaries = [asset["asset_id"] for asset in selected if "canary" in asset["evidence_class"]]
        accepted: list[str] = []
        background_evidence[background] = {
            "required": True,
            "accepted_independent_references": accepted,
            "same_solver_legacy_assets": same_solver,
            "legacy_canaries": canaries,
            "status": "blocked",
            "reason": "no F2 experimental or analytical reference with explicit provenance metadata",
        }
        blockers.append(f"{background}: missing independent F2 reference anchor")
    wrong_family = lab / "data-official/O3_sloshing_motion.h5"
    wrong_family_present = wrong_family.is_file()
    return {
        "status": "blocked" if blockers else "checked",
        "required_backgrounds": list(EXPECTED_BACKGROUNDS),
        "minimum_independent_references": 2,
        "accepted_reference_count": 0,
        "backgrounds": background_evidence,
        "wrong_family_reference_not_counted": {
            "path": _rel(wrong_family, lab),
            "exists": wrong_family_present,
            "reason": "official O3 sloshing is F3, not an F2 rotating-cup reference",
        },
        "blockers": blockers,
    }


def _execution_plan(lab: Path) -> dict[str, Any]:
    script = lab / "scripts/l2_f2r_audit.py"
    command = (
        f"cd {lab} && .venv/bin/python {script} audit "
        "--background slow_center offset_partial "
        "--output campaigns/l2-multifamily/resume-c6b28c8/f2r-audit.json"
    )
    return {
        "gpu_required_for_audit": False,
        "solver_launched_by_this_entry": False,
        "parallel_safe_commands": [command],
        "next_solver_gate": "do not launch an F2R matrix until the static-hold and two-reference blockers are explicitly repaired",
        "gpu_recommendation": {
            "audit": "CPU-only; it can run in parallel with unrelated GPU jobs",
            "future_single_canary": "reserve one idle physical GPU only; use CUDA_VISIBLE_DEVICES=<physical-index> and solver -gpu:0 under the mask",
            "local_a6000": "allocate disjoint GPU UUIDs/indices; one heavy canary per GPU, no blanket eight-GPU matrix",
            "remote_h200": "GPU0, GPU2, or GPU3 are suitable when idle; keep the existing GPU1 workload untouched",
        },
    }


def build_report(
    lab: Path = LAB,
    backgrounds: Iterable[str] = EXPECTED_BACKGROUNDS,
) -> dict[str, Any]:
    requested = tuple(backgrounds)
    unknown = sorted(set(requested) - set(EXPECTED_BACKGROUNDS))
    if unknown:
        raise ValueError(f"unsupported F2R backgrounds: {unknown}")
    all_assets = [audit_asset(spec, lab) for spec in default_asset_specs(lab)]
    selected = [asset for asset in all_assets if asset["background"] in requested or asset["background"].startswith("legacy_")]
    static = _static_cup_check(selected)
    moving = _moving_cup_check(selected)
    reference = _reference_gate(selected, lab)
    blockers = list(static.get("reason") and [static["reason"]] or [])
    blockers.extend(moving["blockers"])
    blockers.extend(reference["blockers"])
    return {
        "schema": SCHEMA,
        "task": "L2-R F2R",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "static and moving cup checks, motion/capture geometry, and two-background reference gate",
        "read_only": True,
        "no_solver_launched": True,
        "requested_backgrounds": list(requested),
        "assets": selected,
        "checks": {
            "static_cup": static,
            "moving_cup": moving,
            "capture_geometry": {
                "status": "checked" if all(asset["capture_geometry"]["status"] == "checked" for asset in selected if asset["background"] in requested) else "blocked",
                "aabb_fallback_used": False,
                "per_asset": {
                    asset["asset_id"]: asset["capture_geometry"]
                    for asset in selected
                    if asset["background"] in requested
                },
            },
            "two_background_reference": reference,
        },
        "decision": {
            "status": "blocked" if blockers else "ready_for_single_canary",
            "qualification_claim": "none; this entry is an audit and does not promote legacy/canary evidence",
            "blockers": blockers,
        },
        "execution_plan": _execution_plan(lab),
    }


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_strip_samples(payload), indent=2, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("audit", "inventory"), nargs="?", default="audit")
    parser.add_argument("--lab", type=Path, default=LAB)
    parser.add_argument("--background", nargs="+", choices=EXPECTED_BACKGROUNDS, default=list(EXPECTED_BACKGROUNDS))
    parser.add_argument("--output", type=Path, help="optional JSON report path; no file is written by default")
    args = parser.parse_args(argv)
    payload = build_report(args.lab.resolve(), args.background)
    if args.output:
        _write_report(args.output.resolve(), payload)
    print(json.dumps(_strip_samples(payload), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
