#!/usr/bin/env python3
"""Convert and audit the completed F3 weak dual-axis native trajectory.

The script is an F3-scoped data adapter.  It delegates BI4 decoding and the
official three-frame PartVTK comparison to ``ds_data02_direct_convert`` and
then performs a streaming Q-I audit over the resulting HDF5.  The audit keeps
the generated typed ``(Zone, Idp)`` axis, checks actual 3-D solver evidence,
records the native initial mass without normalization, and writes finite
top-aperture transport labels and real point-cloud previews.  It never starts
GenCase or a solver and never grants Q-N or production eligibility.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import resource
import re
import time
import xml.etree.ElementTree as ET
from typing import Any, Mapping, Sequence

import h5py
import numpy as np

try:  # package import for tests; direct-file import for the shared runner CLI
    from .ds_data02_direct_convert import DirectConversionError, convert_direct, sha256_file
except ImportError:  # pragma: no cover - exercised by ``python scripts/...``
    from ds_data02_direct_convert import DirectConversionError, convert_direct, sha256_file


SCHEMA = "ds02.f3.weak-dual-audit.v1"
PHYSICAL_BINDING_SCHEMA = "ds-data-02.physical-binding.v1"
REQUIRED_H5 = (
    "time", "particle_id", "particle_zone", "initial_type", "initial_mk",
    "initial_mass", "valid", "type", "mk", "position", "velocity",
    "density", "mass", "pressure",
)
TYPE_NAMES = {0: "fixed", 1: "moving", 2: "floating", 3: "fluid"}


class F3AuditError(RuntimeError):
    """Raised when the F3 evidence contract is incomplete or inconsistent."""


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=_json_default).encode("utf-8")
    ).hexdigest()


def _ref(path: Path) -> dict[str, Any]:
    return {"path": str(path), "exists": path.exists(), "sha256": sha256_file(path) if path.is_file() else None}


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise F3AuditError(f"cannot read JSON provenance: {path}") from exc


def _validate_raw_manifest(path: Path, data_root: Path) -> dict[str, Any]:
    """Check the metadata-only all-frame binding before decoding any frame."""
    manifest = _load_json(path)
    if manifest.get("schema") != "ds02.f3.raw-frame-manifest.v1":
        raise F3AuditError(f"unsupported raw frame manifest schema: {path}")
    source = manifest.get("raw_source", {})
    if Path(str(source.get("root", ""))).resolve() != data_root.resolve():
        raise F3AuditError("raw frame manifest root differs from conversion data root")
    files = source.get("files", [])
    frames = [row for row in files if str(row.get("path", "")).startswith("Part_") and str(row.get("path", "")).endswith(".bi4")]
    expected = sorted(data_root.glob("Part_*.bi4"), key=lambda item: item.name)
    expected_names = [item.name for item in expected]
    manifest_names = [str(row.get("path")) for row in frames]
    if manifest_names != expected_names:
        raise F3AuditError("raw frame manifest does not enumerate the current contiguous BI4 frame set")
    for row, current in zip(frames, expected):
        if int(row.get("bytes", -1)) != current.stat().st_size:
            raise F3AuditError(f"raw frame byte size changed after manifest creation: {current}")
    if int(source.get("frame_count", -1)) != len(expected):
        raise F3AuditError("raw frame manifest frame_count disagrees with data root")
    return manifest


def _usage_snapshot() -> dict[str, float]:
    result: dict[str, float] = {}
    for who, label in ((resource.RUSAGE_SELF, "self"), (resource.RUSAGE_CHILDREN, "children")):
        value = resource.getrusage(who)
        result[f"{label}_user_seconds"] = float(value.ru_utime)
        result[f"{label}_system_seconds"] = float(value.ru_stime)
        result[f"{label}_max_rss_kib"] = float(value.ru_maxrss)
    return result


def _usage_delta(before: Mapping[str, float], after: Mapping[str, float]) -> dict[str, float]:
    return {key: float(after[key] - before.get(key, 0.0)) for key in after}


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise F3AuditError(f"not a numeric value: {value!r}") from exc


def _xml_number(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _xml_vector(node: ET.Element | None, names: tuple[str, ...]) -> list[float] | None:
    if node is None or any(name not in node.attrib for name in names):
        return None
    return [_as_float(node.attrib[name]) for name in names]


def _source_control_from_xml(generated_xml: Path) -> Path | None:
    root = ET.parse(generated_xml).getroot()
    node = root.find(".//acctimesfile")
    if node is None:
        return None
    value = node.get("value")
    if not value:
        return None
    candidate = generated_xml.parent / value
    return candidate if candidate.is_file() else None


def _geometry_evidence(generated_xml: Path, solver_receipt: Mapping[str, Any]) -> dict[str, Any]:
    root = ET.parse(generated_xml).getroot()
    definition = root.find(".//geometry/definition")
    data2d = root.find(".//data2d")
    normals = root.find(".//normals")
    particles = root.find(".//execution/particles")
    if data2d is None or data2d.get("value", "").lower() not in {"false", "0", "no"}:
        raise F3AuditError("generated XML does not explicitly declare data2d=false")
    if normals is None or normals.get("active", "").lower() not in {"true", "1", "yes"}:
        raise F3AuditError("generated XML does not explicitly enable normals")
    if particles is None:
        raise F3AuditError("generated XML has no particle block")
    blocks = []
    for child in particles:
        if child.tag in {"fixed", "moving", "floating", "fluid"}:
            blocks.append({
                "tag": child.tag,
                "begin": int(child.get("begin", "-1")),
                "count": int(child.get("count", "-1")),
                "mk": int(child.get("mk", "-1")),
            })
    geometry_commands = []
    for drawbox in root.findall(".//geometry/commands//drawbox"):
        point = drawbox.find("point")
        size = drawbox.find("size")
        layers = drawbox.find("layers")
        geometry_commands.append({
            "boxfill": (drawbox.findtext("boxfill") or "").strip(),
            "point_m": _xml_vector(point, ("x", "y", "z")),
            "size_m": _xml_vector(size, ("x", "y", "z")),
            "layers": None if layers is None else layers.get("vdp"),
        })
    normal_geometry = normals.find(".//geometryfile")
    normal_file = None
    if normal_geometry is not None and normal_geometry.get("file"):
        normal_file = generated_xml.parent / normal_geometry.get("file").replace("[CaseName]", generated_xml.stem)
    output_root = Path(str(solver_receipt.get("output_root", "")))
    solver_root = output_root / "solver_output"
    normal_outputs = {
        name: _ref(solver_root / name)
        for name in ("CfgInit_Normals.vtk", "CfgInit_NormalsGhost.vtk", "CfgInit_Domain.vtk")
    }
    run_out = solver_root / "Run.out"
    run_text = run_out.read_text(errors="replace") if run_out.is_file() else ""
    if not re.search(r"\*\*\s*3D-Simulation parameters", run_text, re.IGNORECASE):
        raise F3AuditError("solver Run.out lacks the actual 3D-Simulation parameters banner")
    if re.search(r"\*\*\s*2D-Simulation parameters", run_text, re.IGNORECASE):
        raise F3AuditError("solver Run.out contains conflicting 2D evidence")
    loaded = re.search(r"Loaded particles:\s*([\d,]+)", run_text)
    return {
        "generated_xml": _ref(generated_xml),
        "data2d": data2d.get("value"),
        "solver_dimension": 3,
        "definition_dp_m": None if definition is None else _xml_number(definition.get("dp")),
        "particle_blocks": blocks,
        "particle_np": int(particles.get("np", "-1")),
        "particle_nb": int(particles.get("nb", "-1")),
        "geometry_commands": geometry_commands,
        "normals_active": True,
        "normal_geometry_file": None if normal_file is None else _ref(normal_file),
        "normal_outputs": normal_outputs,
        "solver_run_out": _ref(run_out),
        "run_out_3d_banner": True,
        "run_out_loaded_particles": None if loaded is None else int(loaded.group(1).replace(",", "")),
        "control_file_from_generated_xml": None if _source_control_from_xml(generated_xml) is None else _ref(_source_control_from_xml(generated_xml)),
    }


def _native_case_summary(native_path: Path, solver_receipt: Path, solver_log: Path) -> dict[str, Any]:
    value = _load_json(native_path)
    if isinstance(value, list):
        rows = value
    elif isinstance(value, dict) and isinstance(value.get("cases"), list):
        rows = value["cases"]
    else:
        rows = [value]
    case = next((row for row in rows if row.get("case_id") == "F3_DUAL_AXIS_WEAK_006G_004G"), rows[0] if rows else None)
    if not isinstance(case, dict):
        raise F3AuditError(f"native accounting has no F3 case: {native_path}")
    facts = case.get("facts", {})
    if case.get("solver_dimension") != 3:
        raise F3AuditError("native accounting does not confirm solver_dimension=3")
    return {
        "source": _ref(native_path),
        "case_id": case.get("case_id"),
        "attempt_id": case.get("attempt_id"),
        "solver_dimension": case.get("solver_dimension"),
        "receipt": _ref(solver_receipt),
        "run_out": _ref(solver_log),
        "facts": {
            key: facts.get(key)
            for key in (
                "saved_frames", "initial_total_particles", "final_total_particles",
                "initial_fluid_particles", "final_fluid_particles",
                "initial_fixed_particles", "final_fixed_particles",
                "initial_floating_particles", "final_floating_particles",
                "initial_moving_particles", "final_moving_particles", "final_time_s",
                "births", "excluded_interval_sums", "internal_steps",
                "actual_internal_dt_min_s", "actual_internal_dt_max_s",
                "native_population_semantics", "native_exclusion_semantics",
            )
        },
        "q_n_status": case.get("q_n_status"),
        "independent_production_case_increment": case.get("independent_production_case_increment"),
    }


def _csv_row(path: Path, frame: int) -> dict[str, Any] | None:
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        for row in reader:
            if int(row["Part"]) == frame:
                return row
    return None


def _finite_aperture_labels(
    h5_path: Path,
    labels_path: Path,
    timeseries_path: Path,
    *,
    aperture: Mapping[str, float],
    chunk_size: int = 65536,
) -> dict[str, Any]:
    with h5py.File(h5_path, "r") as h5:
        times = h5["time"][:]
        particle_id = h5["particle_id"][:]
        zone = h5["particle_zone"][:]
        initial_type = h5["initial_type"][:]
        initial_mk = h5["initial_mk"][:]
        initial_mass = h5["initial_mass"][:].astype(np.float64)
        fluid_indices = np.flatnonzero(initial_type == 3)
        if fluid_indices.size == 0:
            raise F3AuditError("weak F3 HDF5 contains no type=3 fluid identities")
        top = float(aperture["z_plane_m"])
        x_low, x_high = float(aperture["x_low_m"]), float(aperture["x_high_m"])
        y_low, y_high = float(aperture["y_low_m"]), float(aperture["y_high_m"])
        floor = float(aperture.get("z_low_m", 0.0))
        nfluid = int(fluid_indices.size)
        first_passage = np.full(nfluid, np.nan, dtype=np.float64)
        crossing_count = np.zeros(nfluid, dtype=np.int64)
        positive_crossings = np.zeros(nfluid, dtype=np.int64)
        negative_crossings = np.zeros(nfluid, dtype=np.int64)
        residence_s = np.zeros(nfluid, dtype=np.float64)
        residence_mass_time = np.zeros(nfluid, dtype=np.float64)
        positive_mass = 0.0
        negative_mass = 0.0
        positive_count = 0
        negative_count = 0
        aperture_rejected = 0
        unknown_interval_count = 0
        previous_pos = None
        previous_valid = None
        previous_mass = None
        frame_rows: list[dict[str, Any]] = []
        for frame, current_time in enumerate(times):
            pos = h5["position"][frame, fluid_indices, :].astype(np.float64)
            valid = h5["valid"][frame, fluid_indices].astype(bool)
            mass = h5["mass"][frame, fluid_indices].astype(np.float64)
            valid_mass = np.where(valid & np.isfinite(mass) & (mass > 0), mass, 0.0)
            unknown_mass = float(np.sum(np.where(~valid, np.where(np.isfinite(mass), np.maximum(mass, 0.0), 0.0), 0.0)))
            inside_now = valid & np.isfinite(pos).all(axis=1) & (pos[:, 0] >= x_low) & (pos[:, 0] <= x_high) & (pos[:, 1] >= y_low) & (pos[:, 1] <= y_high) & (pos[:, 2] >= floor) & (pos[:, 2] <= top)
            above_now = valid & np.isfinite(pos).all(axis=1) & (pos[:, 0] >= x_low) & (pos[:, 0] <= x_high) & (pos[:, 1] >= y_low) & (pos[:, 1] <= y_high) & (pos[:, 2] > top)
            frame_rows.append({
                "frame": int(frame), "time_s": float(current_time),
                "valid_fluid_particles": int(valid.sum()),
                "active_fluid_mass_kg": float(np.sum(valid_mass)),
                "unknown_fluid_mass_kg": unknown_mass,
                "inside_aperture_mass_kg": float(np.sum(valid_mass[inside_now])),
                "above_open_top_mass_kg": float(np.sum(valid_mass[above_now])),
            })
            if previous_pos is not None:
                dt_s = float(current_time - times[frame - 1])
                both = previous_valid & valid & np.isfinite(previous_pos).all(axis=1) & np.isfinite(pos).all(axis=1)
                if not np.all(previous_valid & valid):
                    unknown_interval_count += int(np.sum(~(previous_valid & valid)))
                midpoint = 0.5 * (previous_pos + pos)
                inside_mid = both & (midpoint[:, 0] >= x_low) & (midpoint[:, 0] <= x_high) & (midpoint[:, 1] >= y_low) & (midpoint[:, 1] <= y_high) & (midpoint[:, 2] >= floor) & (midpoint[:, 2] <= top)
                residence_s[inside_mid] += dt_s
                residence_mass_time[inside_mid] += np.where(np.isfinite(mass[inside_mid]) & (mass[inside_mid] > 0), mass[inside_mid], 0.0) * dt_s
                up = both & (previous_pos[:, 2] < top) & (pos[:, 2] >= top)
                down = both & (previous_pos[:, 2] > top) & (pos[:, 2] <= top)
                for direction, selected in (("positive", up), ("negative", down)):
                    indices = np.flatnonzero(selected)
                    if indices.size:
                        dz = pos[indices, 2] - previous_pos[indices, 2]
                        fraction = np.divide(top - previous_pos[indices, 2], dz, out=np.zeros(indices.size), where=dz != 0)
                        cross_xy = previous_pos[indices] + fraction[:, None] * (pos[indices] - previous_pos[indices])
                        in_aperture = (cross_xy[:, 0] >= x_low) & (cross_xy[:, 0] <= x_high) & (cross_xy[:, 1] >= y_low) & (cross_xy[:, 1] <= y_high)
                        accepted = indices[in_aperture]
                        aperture_rejected += int((~in_aperture).sum())
                        if direction == "positive":
                            positive_count += int(accepted.size)
                            positive_mass += float(np.sum(mass[accepted])) if accepted.size else 0.0
                            positive_crossings[accepted] += 1
                        else:
                            negative_count += int(accepted.size)
                            negative_mass += float(np.sum(mass[accepted])) if accepted.size else 0.0
                            negative_crossings[accepted] += 1
                        for idx in accepted:
                            crossing_count[idx] += 1
                            crossing_time = float(times[frame - 1] + fraction[np.flatnonzero(indices == idx)[0]] * dt_s)
                            if not math.isfinite(first_passage[idx]):
                                first_passage[idx] = crossing_time
            previous_pos, previous_valid, previous_mass = pos, valid, mass
        final_pos = previous_pos
        final_valid = previous_valid
        final_category: list[str] = []
        for idx in range(nfluid):
            if not bool(final_valid[idx]) or not np.isfinite(final_pos[idx]).all():
                final_category.append("unknown")
            elif x_low <= final_pos[idx, 0] <= x_high and y_low <= final_pos[idx, 1] <= y_high and floor <= final_pos[idx, 2] <= top:
                final_category.append("inside_domain")
            elif x_low <= final_pos[idx, 0] <= x_high and y_low <= final_pos[idx, 1] <= y_high and final_pos[idx, 2] > top:
                final_category.append("above_open_top")
            else:
                final_category.append("outside_finite_aperture")
        per_particle = []
        for idx, particle in enumerate(fluid_indices):
            per_particle.append({
                "zone": int(zone[particle]), "idp": int(particle_id[particle]),
                "initial_mk": int(initial_mk[particle]), "initial_type": 3,
                "initial_mass_kg": float(initial_mass[particle]),
                "first_passage_s": None if not math.isfinite(first_passage[idx]) else float(first_passage[idx]),
                "crossing_count": int(crossing_count[idx]), "repeat_crossings": max(0, int(crossing_count[idx]) - 1),
                "positive_crossings": int(positive_crossings[idx]), "negative_crossings": int(negative_crossings[idx]),
                "residence_time_s": float(residence_s[idx]),
                "residence_mass_time_kg_s": float(residence_mass_time[idx]),
                "final_category": final_category[idx], "final_valid": bool(final_valid[idx]),
            })
        labels = {
            "schema": "ds02.f3.weak-dual-typed-transport.v1",
            "identity_key": "(Zone,Idp)",
            "operator": {
                "plane_z_m": top, "x_aperture_m": [x_low, x_high], "y_aperture_m": [y_low, y_high],
                "crossing_time": "linear interpolation at actual HDF5 times", "mass_unit": "kg",
                "residence_mass_time_unit": "kg*s", "residence_particle_time_unit": "s",
                "initial_region_boxes_not_used": True,
            },
            "aggregate": {
                "fluid_identity_count": nfluid, "initial_fluid_mass_kg": float(np.sum(initial_mass[fluid_indices])),
                "positive_crossings": positive_count, "negative_crossings": negative_count,
                "positive_crossing_mass_kg": positive_mass, "negative_crossing_mass_kg": negative_mass,
                "net_crossing_mass_kg": positive_mass - negative_mass,
                "repeat_crossings": int(np.sum(np.maximum(crossing_count - 1, 0))),
                "aperture_rejected_crossings": aperture_rejected,
                "unknown_interval_particle_events": unknown_interval_count,
                "final_category_counts": {category: final_category.count(category) for category in sorted(set(final_category))},
            },
            "per_particle": per_particle,
            "frame_rows": frame_rows,
        }
    labels_path.parent.mkdir(parents=True, exist_ok=True)
    labels_path.write_text(json.dumps(labels, indent=2, sort_keys=True, default=_json_default) + "\n")
    with timeseries_path.open("w", newline="") as handle:
        fields = list(frame_rows[0]) if frame_rows else ["frame", "time_s"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(frame_rows)
    return {
        "schema": labels["schema"], "labels": _ref(labels_path), "timeseries": _ref(timeseries_path),
        "aggregate": labels["aggregate"], "frame_count": len(frame_rows), "per_particle_count": len(per_particle),
    }


def _render_frame(h5: h5py.File, frame: int, output: Path, *, max_points: int = 12000) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from PIL import Image

    positions = h5["position"][frame]
    valid = h5["valid"][frame]
    types = h5["type"][frame]
    selected = np.flatnonzero(valid)
    if selected.size > max_points:
        selected = selected[np.linspace(0, selected.size - 1, max_points, dtype=np.int64)]
    pos = positions[selected]
    kinds = types[selected]
    colors = np.where(kinds == 3, "#1f77b4", "#777777")
    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=120)
    ax.scatter(pos[:, 0], pos[:, 2], c=colors, s=2, alpha=0.55, linewidths=0)
    ax.set_xlim(-0.49, 0.49)
    ax.set_ylim(-0.03, 0.54)
    ax.set_xlabel("x [m]")
    ax.set_ylabel("z [m]")
    ax.set_title(f"F3 weak dual axis, frame {frame}, t={float(h5['time'][frame]):.6f} s")
    ax.grid(alpha=0.18)
    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png")
    plt.close(fig)
    buffer.seek(0)
    image = Image.open(buffer).convert("RGB")
    image.save(output, format="PNG")
    image.close()


def _previews(h5_path: Path, preview_dir: Path) -> dict[str, Any]:
    from PIL import Image

    preview_dir.mkdir(parents=True, exist_ok=True)
    with h5py.File(h5_path, "r") as h5:
        frames = int(h5["time"].shape[0])
        key_indices = [0, frames // 2, frames - 1]
        keyframes = []
        for frame in key_indices:
            path = preview_dir / f"keyframe_{frame:04d}.png"
            _render_frame(h5, frame, path)
            keyframes.append({"frame": frame, "time_s": float(h5["time"][frame]), "file": _ref(path), "display_only_downsample": True})
        gif_indices = np.linspace(0, frames - 1, 21, dtype=np.int64).tolist()
        gif_images = []
        for frame in gif_indices:
            scratch = preview_dir / f".gif_frame_{frame:04d}.png"
            _render_frame(h5, int(frame), scratch, max_points=8000)
            image = Image.open(scratch).convert("RGB")
            gif_images.append(image.copy())
            scratch.unlink()
            image.close()
        gif_path = preview_dir / "actual_trajectory.gif"
        first, rest = gif_images[0], gif_images[1:]
        first.save(gif_path, format="GIF", save_all=True, append_images=rest, duration=120, loop=0, optimize=False)
        for image in gif_images:
            image.close()
    return {"schema": "ds02.f3.actual-preview.v1", "full_h5_retained": True, "keyframes": keyframes, "gif": _ref(gif_path), "gif_frames": gif_indices}


def _audit_h5(
    *, h5_path: Path, conversion_report_path: Path, generated_xml: Path, solver_log: Path,
    solver_receipt: Path, gencase_receipt: Path, owner_metadata: Path, native_accounting: Path,
    operators: Path, labels_path: Path, timeseries_path: Path, preview_dir: Path, raw_manifest: Path,
) -> dict[str, Any]:
    started = time.monotonic()
    before_usage = _usage_snapshot()
    owner = _load_json(owner_metadata)
    if owner.get("physical_binding", {}).get("schema") != PHYSICAL_BINDING_SCHEMA:
        raise F3AuditError("F3 owner metadata lacks explicit physical_binding.v1")
    binding = owner["physical_binding"]
    conversion = _load_json(conversion_report_path)
    geometry = _geometry_evidence(generated_xml, _load_json(solver_receipt))
    native = _native_case_summary(native_accounting, solver_receipt, solver_log)
    expected_mass = float(binding["initial_state"]["initial_mass_total_kg"])
    with h5py.File(h5_path, "r") as h5:
        missing = [name for name in REQUIRED_H5 if name not in h5]
        if missing:
            raise F3AuditError(f"HDF5 missing required datasets: {missing}")
        frames, particles = h5["time"].shape[0], h5["particle_id"].shape[0]
        if h5["position"].shape != (frames, particles, 3):
            raise F3AuditError("position shape is not (frames, particles, 3)")
        ids = h5["particle_id"][:]
        zones = h5["particle_zone"][:]
        typed_unique = len(set(zip(zones.tolist(), ids.tolist()))) == particles
        if not typed_unique:
            raise F3AuditError("typed (Zone,Idp) initial identity axis is not unique")
        times = h5["time"][:]
        finite_time = bool(np.isfinite(times).all())
        increasing = bool(np.all(np.diff(times) > 0))
        if not finite_time or not increasing:
            raise F3AuditError("HDF5 time is not finite and strictly increasing")
        initial_type = h5["initial_type"][:]
        initial_mk = h5["initial_mk"][:]
        initial_mass = h5["initial_mass"][:].astype(np.float64)
        if np.any(~np.isfinite(initial_mass)) or np.any(initial_mass <= 0):
            raise F3AuditError("initial mass is not finite and positive")
        initial_counts = {TYPE_NAMES[kind]: int(np.sum(initial_type == kind)) for kind in range(4)}
        initial_mass_by_type = {TYPE_NAMES[kind]: float(np.sum(initial_mass[initial_type == kind])) for kind in range(4)}
        valid_binary = True
        finite_positive = True
        missing_frames = 0
        missing_by_type = {str(kind): 0 for kind in range(4)}
        first_missing_frame: dict[str, int] = {}
        ever_missing = np.zeros(particles, dtype=bool)
        revival_count = 0
        frame_rows = []
        for frame in range(frames):
            valid = h5["valid"][frame].astype(bool)
            valid_binary = valid_binary and bool(np.isin(h5["valid"][frame], [False, True]).all())
            missing = ~valid
            if missing.any():
                missing_frames += 1
                for kind in range(4):
                    count = int(np.sum(missing & (initial_type == kind)))
                    missing_by_type[str(kind)] += count
                    if count and str(kind) not in first_missing_frame:
                        first_missing_frame[str(kind)] = frame
            revival_count += int(np.sum(ever_missing & valid))
            ever_missing |= missing
            density = h5["density"][frame]
            mass = h5["mass"][frame]
            active = valid & np.isfinite(density) & np.isfinite(mass) & (density > 0) & (mass > 0)
            finite_positive = finite_positive and bool(np.all(active == valid))
            frame_rows.append({
                "frame": frame, "time_s": float(times[frame]), "valid_particles": int(valid.sum()),
                "missing_particles": int(missing.sum()), "active_mass_kg": float(np.nansum(np.where(active, mass, 0.0))),
            })
        final_valid = h5["valid"][-1].astype(bool)
        final_type_counts = {TYPE_NAMES[kind]: int(np.sum(final_valid & (h5["type"][-1] == kind))) for kind in range(4)}
        initial_fluid_mass = initial_mass_by_type["fluid"]
        mass_relative_error = abs(initial_fluid_mass - expected_mass) / expected_mass
        initial_mass_check = bool(mass_relative_error <= float(_load_json(operators)["initial_mass"]["relative_error_budget"]))
        source_attrs = {key: (value.item() if hasattr(value, "item") else value) for key, value in h5.attrs.items() if key in {
            "schema", "conversion_complete", "solver_dimension", "coordinate_frame", "identity_key",
            "units_json", "physical_condition_sha256", "numerical_parameters_sha256", "geometry_reference_sha256",
            "control_reference_sha256", "source_raw_tree_sha256_before", "source_raw_tree_sha256_after",
            "source_tree_unchanged", "q_i_status", "q_n_status", "production_eligibility",
        }}
        source_attrs = {
            key: value.decode("utf-8") if isinstance(value, (bytes, bytearray)) else value
            for key, value in source_attrs.items()
        }
    if not valid_binary or not finite_positive:
        raise F3AuditError("valid/mass/density Q-I checks failed")
    if not geometry["normal_outputs"]["CfgInit_Normals.vtk"]["exists"]:
        raise F3AuditError("actual solver normal initialization output is missing")
    source_control = _source_control_from_xml(generated_xml)
    owner_control_sha = owner.get("source_control_sha256")
    control_binding = {
        "owner_source_control_sha256": owner_control_sha,
        "generated_control_sha256": None if source_control is None else sha256_file(source_control),
        "matches_owner": bool(source_control and owner_control_sha and sha256_file(source_control) == owner_control_sha),
        "source_control": None if source_control is None else _ref(source_control),
    }
    if owner_control_sha and not control_binding["matches_owner"]:
        raise F3AuditError("generated control file does not match the registered weak-control hash")
    aperture = {
        "z_plane_m": float(binding["geometry"]["tank"]["low_m"][2] + binding["geometry"]["tank"]["size_m"][2]),
        "x_low_m": float(binding["geometry"]["tank"]["low_m"][0]),
        "x_high_m": float(binding["geometry"]["tank"]["low_m"][0] + binding["geometry"]["tank"]["size_m"][0]),
        "y_low_m": float(binding["geometry"]["tank"]["low_m"][1]),
        "y_high_m": float(binding["geometry"]["tank"]["low_m"][1] + binding["geometry"]["tank"]["size_m"][1]),
        "z_low_m": float(binding["geometry"]["tank"]["low_m"][2]),
    }
    transport = _finite_aperture_labels(h5_path, labels_path, timeseries_path, aperture=aperture)
    previews = _previews(h5_path, preview_dir)
    report = {
        "schema": SCHEMA,
        "audit_status": "completed_actual_read_only_qi",
        "audit_claim": "F3 weak dual-axis typed Q-I/reference evidence only; Q-N and production are not assessed",
        "case_id": owner["physical_case_id"], "family_id": "F3", "mechanism_id": owner["mechanism_id"],
        "hdf5": _ref(h5_path), "conversion_report": _ref(conversion_report_path),
        "raw_frame_manifest": _ref(raw_manifest),
        "conversion": {
            "schema": conversion.get("schema"), "frames": conversion.get("frames"), "particles": conversion.get("particles"),
            "solver_dimension": conversion.get("solver_dimension"), "partvtk_validation": conversion.get("partvtk_validation"),
            "source_tree": conversion.get("source_provenance", {}).get("raw_tree"),
            "physical_condition_sha256": conversion.get("hash_scopes", {}).get("physical_condition_sha256"),
            "numerical_parameters_sha256": conversion.get("hash_scopes", {}).get("numerical_parameters_sha256"),
        },
        "physical_binding": {
            "schema": binding["schema"], "sha256": _canonical_hash(binding),
            "excludes_resolution_and_numeric": True, "binding": binding,
            "control_hash": control_binding,
        },
        "geometry_initialization": geometry,
        "native_accounting": native,
        "hdf5_qi": {
            "frames": frames, "particles": particles, "time_start_s": float(times[0]), "time_end_s": float(times[-1]),
            "time_finite": finite_time, "time_strictly_increasing": increasing,
            "valid_binary": valid_binary, "finite_positive_active_state": finite_positive,
            "typed_identity": {"key": "(Zone,Idp)", "unique": typed_unique, "zone_count": len(set(zones.tolist()))},
            "initial_type_counts": initial_counts, "final_type_counts": final_type_counts,
            "initial_mass_by_type_kg": initial_mass_by_type,
            "initial_fluid_mass_kg": initial_fluid_mass, "expected_continuum_mass_kg": expected_mass,
            "initial_mass_relative_error": mass_relative_error, "initial_mass_within_budget": initial_mass_check,
            "missing_frames": missing_frames, "missing_by_initial_type_frame_events": missing_by_type,
            "first_missing_frame_by_initial_type": first_missing_frame, "revival_count": revival_count,
            "frame_rows": frame_rows,
            "attrs": source_attrs,
        },
        "finite_aperture_transport": {"aperture": aperture, **transport},
        "preview": previews,
        "operators": _ref(operators),
        "q_i_status": "evidence_complete_for_conversion/lifecycle/static geometry/finite aperture; no Q-N",
        "q_n_status": "not_assessed",
        "production_eligibility": "not_evaluated",
        "resource": {"wall_seconds": time.monotonic() - started, "usage": _usage_delta(before_usage, _usage_snapshot())},
    }
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--generated-xml", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--conversion-report", type=Path, required=True)
    parser.add_argument("--audit-report", type=Path, required=True)
    parser.add_argument("--decoder", type=Path, required=True)
    parser.add_argument("--partvtk", type=Path, required=True)
    parser.add_argument("--validation-dir", type=Path, required=True)
    parser.add_argument("--solver-log", type=Path, required=True)
    parser.add_argument("--solver-receipt", type=Path, required=True)
    parser.add_argument("--gencase-receipt", type=Path, required=True)
    parser.add_argument("--owner-metadata", type=Path, required=True)
    parser.add_argument("--native-accounting", type=Path, required=True)
    parser.add_argument("--raw-manifest", type=Path, required=True)
    parser.add_argument("--operators", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--timeseries", type=Path, required=True)
    parser.add_argument("--preview-dir", type=Path, required=True)
    parser.add_argument("--particle-chunk", type=int, default=65536)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        raw_manifest = _validate_raw_manifest(args.raw_manifest, args.data_root)
        conversion = convert_direct(
            data_root=args.data_root, generated_xml=args.generated_xml, output=args.output,
            report_path=args.conversion_report, decoder=args.decoder, partvtk=args.partvtk,
            validation_dir=args.validation_dir, solver_log=args.solver_log,
            solver_receipt=args.solver_receipt, gencase_receipt=args.gencase_receipt,
            owner_metadata=args.owner_metadata, particle_chunk=args.particle_chunk,
            run_partvtk=True, keep_validation_csv=True,
        )
        report = _audit_h5(
            h5_path=args.output, conversion_report_path=args.conversion_report,
            generated_xml=args.generated_xml, solver_log=args.solver_log,
            solver_receipt=args.solver_receipt, gencase_receipt=args.gencase_receipt,
            owner_metadata=args.owner_metadata, native_accounting=args.native_accounting,
            operators=args.operators, labels_path=args.labels, timeseries_path=args.timeseries,
            preview_dir=args.preview_dir, raw_manifest=args.raw_manifest,
        )
        report["conversion_report_sha256"] = sha256_file(args.conversion_report)
        args.audit_report.parent.mkdir(parents=True, exist_ok=True)
        args.audit_report.write_text(json.dumps(report, indent=2, sort_keys=True, default=_json_default) + "\n")
    except (DirectConversionError, F3AuditError, OSError, ValueError) as exc:
        print(f"F3 weak audit failed: {exc}")
        return 2
    print(json.dumps({"h5": str(args.output), "audit_report": str(args.audit_report), "frames": report["hdf5_qi"]["frames"], "particles": report["hdf5_qi"]["particles"], "partvtk_all_passed": report["conversion"]["partvtk_validation"]["all_passed"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
