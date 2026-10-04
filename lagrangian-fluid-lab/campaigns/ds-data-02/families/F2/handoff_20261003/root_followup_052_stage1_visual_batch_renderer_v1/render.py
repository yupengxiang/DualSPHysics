"""Render a complete DS-DATA-02 temporal XDMF product in ParaView.

This is a source-only renderer.  It reads the immutable XDMF entry through
ParaView's XdmfReader, keeps every saved time and point field in the reader,
and applies filters only to display proxies.  It never opens or rewrites the
trajectory source and it does not certify numerical precision.

The module deliberately imports ParaView, VTK and Pillow only inside
``render_case``.  That keeps the manifest, camera and type-alias API usable by
ordinary Python checks while the real render remains a ``pvpython`` action
owned by the root dispatcher.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


MANIFEST_SCHEMA = "ds02.stage1.paraview-temporal-product.v1"
REPORT_SCHEMA = "ds02.stage1.paraview-full-animation-integrity.v1"
REQUEST_SCHEMA = "ds02.stage1.paraview-batch-render-request.v1"
DEFAULT_TYPE_CODES: dict[str, tuple[int, ...]] = {
    "fixed": (0,),
    "moving": (1,),
    "floating": (2,),
    "fluid": (3,),
}
DEFAULT_FINITE_FIELDS = ("mass", "velocity", "density", "pressure")
REQUIRED_POINT_FIELDS = ("valid", "particle_id", "particle_zone", "type")
HEX64 = set("0123456789abcdefABCDEF")


class RendererError(ValueError):
    """Raised for a source or manifest contract violation before rendering."""


def sha256(path: Path) -> str:
    """Hash a file in bounded chunks without loading a trajectory into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _finite_number(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise RendererError(f"{label} must be a finite number") from exc
    if not math.isfinite(number):
        raise RendererError(f"{label} must be a finite number")
    return number


def _field_names(manifest: Mapping[str, Any]) -> set[str]:
    fields = manifest.get("fields", {})
    if isinstance(fields, Mapping):
        return {str(name) for name in fields}
    if isinstance(fields, Sequence) and not isinstance(fields, (str, bytes)):
        return {str(name) for name in fields}
    raise RendererError("manifest fields must be an object or a list")


def _normalise_bounds(raw: Any, label: str = "bounds") -> tuple[tuple[float, float], ...]:
    """Convert common six-value or three-pair bounds representations."""

    if isinstance(raw, Mapping):
        if {"xmin", "xmax", "ymin", "ymax", "zmin", "zmax"} <= set(raw):
            raw = [
                [raw["xmin"], raw["xmax"]],
                [raw["ymin"], raw["ymax"]],
                [raw["zmin"], raw["zmax"]],
            ]
        else:
            raise RendererError(f"{label} mapping must contain xmin/xmax/ymin/ymax/zmin/zmax")
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        values = list(raw)
    else:
        raise RendererError(f"{label} must be a six-value list or three min/max pairs")
    if len(values) == 6 and not any(isinstance(item, Sequence) and not isinstance(item, (str, bytes)) for item in values):
        values = [values[0:2], values[2:4], values[4:6]]
    if len(values) != 3 or any(
        not isinstance(item, Sequence) or isinstance(item, (str, bytes)) or len(item) != 2
        for item in values
    ):
        raise RendererError(f"{label} must contain three [min, max] pairs")
    result: list[tuple[float, float]] = []
    for index, pair in enumerate(values):
        low = _finite_number(pair[0], f"{label}[{index}][0]")
        high = _finite_number(pair[1], f"{label}[{index}][1]")
        if high < low:
            raise RendererError(f"{label}[{index}] has max below min")
        result.append((low, high))
    if all(high == low for low, high in result):
        raise RendererError(f"{label} has no extent")
    return tuple(result)


def _merge_bounds(
    current: tuple[tuple[float, float], ...] | None,
    candidate: Sequence[Sequence[float]],
) -> tuple[tuple[float, float], ...]:
    candidate_bounds = _normalise_bounds(candidate, "candidate bounds")
    if current is None:
        return candidate_bounds
    return tuple(
        (min(current[index][0], candidate_bounds[index][0]),
         max(current[index][1], candidate_bounds[index][1]))
        for index in range(3)
    )


def _normalise_codes(value: Any, label: str) -> tuple[int, ...]:
    if isinstance(value, bool):
        raise RendererError(f"{label} must contain integer type codes")
    values = [value] if isinstance(value, (int, float)) else value
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise RendererError(f"{label} must be an integer or a list of integers")
    result: list[int] = []
    for code in values:
        if isinstance(code, bool):
            raise RendererError(f"{label} must contain integer type codes")
        try:
            integer = int(code)
        except (TypeError, ValueError) as exc:
            raise RendererError(f"{label} must contain integer type codes") from exc
        if float(code) != integer:
            raise RendererError(f"{label} must contain integer type codes")
        if integer not in result:
            result.append(integer)
    if not result:
        raise RendererError(f"{label} cannot be empty")
    return tuple(result)


def resolve_type_codes(manifest: Mapping[str, Any]) -> dict[str, tuple[int, ...]]:
    """Resolve native type aliases without changing any source array values.

    The exporter historically calls this field ``type_codes``.  Newer root
    manifests may call it ``type_aliases``; both forms are accepted so an F2
    case can bind to a family-specific native schema without a conversion.
    """

    aliases: Mapping[str, Any] = {}
    for key in ("type_aliases", "type_codes"):
        value = manifest.get(key)
        if value is not None:
            if not isinstance(value, Mapping):
                raise RendererError(f"manifest {key} must be an object")
            aliases = {**aliases, **value}
    resolved: dict[str, tuple[int, ...]] = {}
    for name, defaults in DEFAULT_TYPE_CODES.items():
        value = aliases.get(name)
        if value is None:
            # A few source ledgers use ``*_type`` names while retaining the
            # native integer values.  This is an alias only, never a remap.
            value = aliases.get(f"{name}_type", defaults)
        resolved[name] = _normalise_codes(value, f"type alias {name}")
    return resolved


def resolve_boundary_codes(manifest: Mapping[str, Any], type_codes: Mapping[str, tuple[int, ...]]) -> tuple[int, ...]:
    value = manifest.get("boundary_type_codes", manifest.get("boundary_codes"))
    if value is None:
        value = type_codes["fixed"]
    return _normalise_codes(value, "boundary type codes")


def validate_manifest(manifest: Mapping[str, Any]) -> None:
    """Validate the portable contract before any ParaView object is created."""

    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise RendererError(f"unsupported manifest schema: {manifest.get('schema')!r}")
    xdmf = manifest.get("xdmf")
    if not isinstance(xdmf, str) or not xdmf:
        raise RendererError("manifest xdmf must be a non-empty path")
    digest = manifest.get("xdmf_sha256")
    if not isinstance(digest, str) or len(digest) != 64 or not set(digest) <= HEX64:
        raise RendererError("manifest xdmf_sha256 must be a 64-character hexadecimal digest")
    try:
        frames = int(manifest["frames"])
        particles = int(manifest["particles"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RendererError("manifest frames and particles must be positive integers") from exc
    if frames <= 0 or particles <= 0:
        raise RendererError("manifest frames and particles must be positive integers")
    times = manifest.get("actual_time_s")
    if not isinstance(times, Sequence) or isinstance(times, (str, bytes)) or len(times) != frames:
        raise RendererError("actual_time_s must contain exactly one value per saved frame")
    numeric_times = [_finite_number(value, f"actual_time_s[{index}]") for index, value in enumerate(times)]
    if any(later <= earlier for earlier, later in zip(numeric_times, numeric_times[1:])):
        raise RendererError("actual_time_s must be strictly increasing")
    fields = _field_names(manifest)
    missing = sorted(set(REQUIRED_POINT_FIELDS) - fields)
    if missing:
        raise RendererError(f"manifest is missing required point fields: {', '.join(missing)}")
    finite_fields = manifest.get("finite_fields", DEFAULT_FINITE_FIELDS)
    if not isinstance(finite_fields, Sequence) or isinstance(finite_fields, (str, bytes)):
        raise RendererError("finite_fields must be a list")
    missing_finite = sorted(set(str(name) for name in finite_fields) - fields)
    if missing_finite:
        raise RendererError(f"finite fields are absent from the manifest: {', '.join(missing_finite)}")
    resolve_type_codes(manifest)
    resolve_boundary_codes(manifest, resolve_type_codes(manifest))
    if "camera_bounds" in manifest:
        _normalise_bounds(manifest["camera_bounds"], "camera_bounds")
    if "domain_bounds" in manifest:
        _normalise_bounds(manifest["domain_bounds"], "domain_bounds")


def load_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise RendererError("manifest root must be an object")
    validate_manifest(manifest)
    source = Path(manifest["xdmf"])
    if not source.is_absolute():
        source = (path.parent / source).resolve()
        manifest["xdmf"] = str(source)
    if not source.is_file():
        raise RendererError(f"XDMF source does not exist: {source}")
    actual = sha256(source)
    if actual != manifest["xdmf_sha256"]:
        raise RendererError(f"XDMF source SHA differs: {actual} != {manifest['xdmf_sha256']}")
    return manifest


def parse_frame_selection(value: str | None, frame_count: int) -> list[int]:
    """Parse a comma-separated diagnostic selection, retaining source order."""

    if value is None or not value.strip():
        return list(range(frame_count))
    try:
        selection = [int(piece.strip()) for piece in value.split(",") if piece.strip()]
    except ValueError as exc:
        raise RendererError("diagnostic frame selection must be comma-separated integers") from exc
    if not selection:
        raise RendererError("diagnostic frame selection cannot be empty")
    if len(set(selection)) != len(selection):
        raise RendererError("diagnostic frame selection cannot contain duplicates")
    if any(frame < 0 or frame >= frame_count for frame in selection):
        raise RendererError("diagnostic frame selection contains an out-of-range frame")
    return selection


def camera_for_bounds(
    bounds: Any,
    *,
    margin: float = 1.28,
    cutaway_fraction: float = 0.5,
) -> dict[str, Any]:
    """Create stable, parallel-projection cameras from native data bounds.

    The parallel scale is based on the 3-D diagonal, so a narrow family and a
    tall family both remain inside the frame.  The camera never changes the
    source coordinates or inserts a clipping filter into the reader.
    """

    normalised = _normalise_bounds(bounds)
    if not math.isfinite(margin) or margin <= 1.0:
        raise RendererError("camera margin must be finite and greater than one")
    if not 0.0 < cutaway_fraction < 1.0:
        raise RendererError("cutaway_fraction must lie strictly between zero and one")
    center = tuple((low + high) / 2.0 for low, high in normalised)
    extent = tuple(max(high - low, 1.0e-9) for low, high in normalised)
    diagonal = math.sqrt(sum(value * value for value in extent))
    parallel_scale = max(diagonal * margin, 1.0e-6)
    distance = max(diagonal * 2.5, 1.0)
    iso_direction = (1.1, -1.6, 0.95)
    direction_norm = math.sqrt(sum(value * value for value in iso_direction))
    iso_position = tuple(
        center[index] + distance * iso_direction[index] / direction_norm for index in range(3)
    )
    side_position = (center[0], center[1] - distance, center[2])
    cutaway_y = normalised[1][0] + (normalised[1][1] - normalised[1][0]) * cutaway_fraction
    view = {
        "focal_point": list(center),
        "parallel_projection": True,
        "parallel_scale": parallel_scale,
        "view_up": [0.0, 0.0, 1.0],
    }
    return {
        "bounds": [list(pair) for pair in normalised],
        "focal_point": list(center),
        "cutaway_y": cutaway_y,
        "parallel_scale": parallel_scale,
        "views": [
            {**view, "position": list(iso_position), "name": "isometric"},
            {**view, "position": list(side_position), "name": "transverse_side"},
        ],
    }


def _bounds_from_points(points: Any, valid: Any) -> tuple[tuple[float, float], ...] | None:
    """Return finite active point bounds using numpy-like indexing.

    This helper lives behind the ParaView runtime and intentionally avoids a
    second source reader.  ``points`` and ``valid`` are VTK-to-numpy arrays.
    """

    import numpy as np

    point_array = np.asarray(points)
    valid_array = np.asarray(valid).astype(bool)
    if point_array.ndim != 2 or point_array.shape[1] != 3:
        raise RendererError(f"source points must have shape (N, 3), got {point_array.shape}")
    mask = valid_array & np.isfinite(point_array).all(axis=1)
    if not mask.any():
        return None
    selected = point_array[mask]
    return tuple((float(selected[:, index].min()), float(selected[:, index].max())) for index in range(3))


def _iter_leaf_data(data: Any) -> Iterable[Any]:
    if data.IsA("vtkCompositeDataSet"):
        iterator = data.NewIterator()
        iterator.SkipEmptyNodesOn()
        iterator.InitTraversal()
        while not iterator.IsDoneWithTraversal():
            current = iterator.GetCurrentDataObject()
            if current is not None:
                yield current
            iterator.GoToNextItem()
    else:
        yield data


def _fetch_dataset(reader: Any, servermanager: Any) -> Any:
    blocks = [block for block in _iter_leaf_data(servermanager.Fetch(reader)) if block is not None]
    if len(blocks) != 1:
        raise RendererError(f"XDMF reader returned {len(blocks)} non-empty blocks; expected one point set")
    return blocks[0]


def _array(point_data: Any, name: str, vtk_to_numpy: Any) -> Any:
    array = point_data.GetArray(name)
    if array is None:
        raise RendererError(f"ParaView source did not expose point field {name!r}")
    return vtk_to_numpy(array)


def _configure_native_display(display: Any, color: Sequence[float], *, representation: str, point_size: float, opacity: float = 1.0) -> None:
    """Use native unlit colors and avoid ParaView's ColorBy(None) path."""

    display.Representation = representation
    display.PointSize = point_size
    display.Opacity = opacity
    # An empty POINTS array name is the supported uncolored/native-color API;
    # ColorBy(None) asks ParaView for a NONE association and fails on 6.1.
    display.ColorArrayName = ["POINTS", ""]
    display.DiffuseColor = list(color)
    display.AmbientColor = list(color)
    display.Ambient = 1.0
    display.Diffuse = 0.0
    if hasattr(display, "Specular"):
        display.Specular = 0.0


def _threshold(input_proxy: Any, codes: Sequence[int], name: str, *, label: str) -> Any:
    from paraview.simple import AppendDatasets, Threshold

    unique = tuple(dict.fromkeys(int(code) for code in codes))
    proxies: list[Any] = []
    for code in unique:
        proxy = Threshold(Input=input_proxy)
        proxy.Scalars = ["POINTS", name]
        proxy.LowerThreshold = code
        proxy.UpperThreshold = code
        proxies.append(proxy)
    if len(proxies) == 1:
        return proxies[0]
    merged = AppendDatasets(Input=proxies)
    return merged


def _build_display_pipeline(reader: Any, manifest: Mapping[str, Any], camera: Mapping[str, Any]) -> dict[str, Any]:
    from paraview.simple import Clip, CreateLayout, CreateView, Outline, Show, AssignViewToLayout, Threshold

    type_codes = resolve_type_codes(manifest)
    boundary_codes = resolve_boundary_codes(manifest, type_codes)
    active = Threshold(Input=reader)
    active.Scalars = ["POINTS", "valid"]
    active.LowerThreshold = 1
    active.UpperThreshold = 1
    fluid = _threshold(active, type_codes["fluid"], "type", label="native fluid")
    moving = _threshold(active, type_codes["moving"], "type", label="native moving type-1")
    floating = _threshold(active, type_codes["floating"], "type", label="native floating type-2")
    boundary = _threshold(active, boundary_codes, "type", label="native fixed boundary")

    # This clip belongs only to the boundary display branch.  The reader and
    # all point fields remain complete in the XMF/PVSM source entry.
    cutaway = Clip(Input=boundary)
    cutaway.ClipType = "Plane"
    cutaway.ClipType.Origin = [
        float(camera["focal_point"][0]),
        float(camera["cutaway_y"]),
        float(camera["focal_point"][2]),
    ]
    cutaway.ClipType.Normal = [0.0, 1.0, 0.0]
    keep_side = str(manifest.get("cutaway_keep_side", "positive"))
    if keep_side not in {"positive", "negative"}:
        raise RendererError("cutaway_keep_side must be positive or negative")
    # ParaView versions expose either Invert or InsideOut for vtkClipDataSet;
    # use whichever property is available while keeping the plane fixed.
    invert = keep_side == "negative"
    if hasattr(cutaway, "Invert"):
        cutaway.Invert = invert
    elif hasattr(cutaway, "InsideOut"):
        cutaway.InsideOut = invert
    boundary_outline = Outline(Input=cutaway)

    layout = CreateLayout(name=f"{manifest.get('physical_case_id', 'DS02')} full saved animation")
    views = [CreateView("RenderView"), CreateView("RenderView")]
    layout.SplitHorizontal(0, 0.5)
    background = manifest.get("background", [0.96, 0.97, 0.99])
    if not isinstance(background, Sequence) or len(background) != 3:
        raise RendererError("background must contain three RGB values")
    colors = {
        "boundary": manifest.get("boundary_color", [0.40, 0.45, 0.50]),
        "fluid": manifest.get("fluid_color", [0.00, 0.38, 0.85]),
        "moving": manifest.get("moving_color", [1.00, 0.45, 0.05]),
        "floating": manifest.get("floating_color", [0.88, 0.05, 0.05]),
    }
    for index, view in enumerate(views):
        AssignViewToLayout(view=view, layout=layout, hint=1 + index)
        view.ViewSize = list(manifest.get("view_size", [640, 480]))
        view.Background = list(background)
        view.OrientationAxesVisibility = 1
        view.UseColorPaletteForBackground = 0
        boundary_display = Show(boundary_outline, view)
        _configure_native_display(boundary_display, colors["boundary"], representation="Wireframe", point_size=2.0, opacity=0.55)
        fluid_display = Show(fluid, view)
        _configure_native_display(fluid_display, colors["fluid"], representation="Points", point_size=2.0)
        moving_display = Show(moving, view)
        _configure_native_display(moving_display, colors["moving"], representation="Points", point_size=4.0)
        floating_display = Show(floating, view)
        _configure_native_display(floating_display, colors["floating"], representation="Points", point_size=4.0)
        spec = camera["views"][index]
        view.CameraFocalPoint = list(spec["focal_point"])
        view.CameraPosition = list(spec["position"])
        view.CameraViewUp = list(spec["view_up"])
        view.CameraParallelProjection = 1
        view.CameraParallelScale = float(spec["parallel_scale"])

    return {
        "active": active,
        "fluid": fluid,
        "moving": moving,
        "floating": floating,
        "boundary": boundary,
        "cutaway": cutaway,
        "boundary_outline": boundary_outline,
        "layout": layout,
        "views": views,
    }


def _scan_native_bounds(reader: Any, times: Sequence[float], servermanager: Any, vtk_to_numpy: Any) -> tuple[tuple[float, float], ...]:
    bounds: tuple[tuple[float, float], ...] | None = None
    for time in times:
        reader.UpdatePipeline(time=float(time))
        data = _fetch_dataset(reader, servermanager)
        points = vtk_to_numpy(data.GetPoints().GetData())
        point_data = data.GetPointData()
        valid = _array(point_data, "valid", vtk_to_numpy)
        candidate = _bounds_from_points(points, valid)
        if candidate is not None:
            bounds = _merge_bounds(bounds, candidate)
    if bounds is None:
        raise RendererError("no finite valid source points were available for camera bounds")
    return bounds


def _frame_diagnostics(
    data: Any,
    manifest: Mapping[str, Any],
    type_codes: Mapping[str, tuple[int, ...]],
    identity: dict[str, Any] | None,
    vtk_to_numpy: Any,
    np: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    point_data = data.GetPointData()
    vtk_points = data.GetPoints()
    if vtk_points is None:
        raise RendererError("source dataset has no point coordinates")
    points = np.asarray(vtk_to_numpy(vtk_points.GetData()))
    if points.ndim != 2 or points.shape[1] != 3:
        raise RendererError(f"source points must have shape (N, 3), got {points.shape}")
    expected_particles = int(manifest["particles"])
    if len(points) != expected_particles:
        raise RendererError(f"source point count {len(points)} differs from manifest {expected_particles}")
    valid_raw = np.asarray(_array(point_data, "valid", vtk_to_numpy))
    if valid_raw.ndim != 1 or len(valid_raw) != expected_particles:
        raise RendererError("valid field does not share the particle axis")
    if not np.isfinite(valid_raw).all() or not np.isin(valid_raw, [0, 1]).all():
        raise RendererError("valid field contains values other than finite 0/1")
    valid = valid_raw.astype(bool)
    types = np.asarray(_array(point_data, "type", vtk_to_numpy))
    ids = np.asarray(_array(point_data, "particle_id", vtk_to_numpy))
    zones = np.asarray(_array(point_data, "particle_zone", vtk_to_numpy))
    if any(array.ndim != 1 or len(array) != expected_particles for array in (types, ids, zones)):
        raise RendererError("type, particle_id and particle_zone must be one-dimensional particle fields")
    if identity is None:
        identity = {
            "particle_id": ids.copy(),
            "particle_zone": zones.copy(),
            "baseline_frame": None,
        }
    else:
        if not np.array_equal(ids, identity["particle_id"]):
            raise RendererError("particle_id changed between saved frames")
        if not np.array_equal(zones, identity["particle_zone"]):
            raise RendererError("particle_zone changed between saved frames")
    finite_fields: dict[str, Any] = {}
    for name in manifest.get("finite_fields", DEFAULT_FINITE_FIELDS):
        values = np.asarray(_array(point_data, str(name), vtk_to_numpy))
        if values.shape[0] != expected_particles:
            raise RendererError(f"finite field {name!r} does not share the particle axis")
        finite_active = bool(np.isfinite(values[valid]).all())
        finite_fields[str(name)] = {
            "finite_active": finite_active,
            "nonfinite_active": int(np.size(values[valid]) - np.isfinite(values[valid]).sum()),
        }
        if not finite_active:
            raise RendererError(f"finite field {name!r} contains a non-finite active value")
    finite_positions = np.isfinite(points[valid]).all()
    if not finite_positions:
        raise RendererError("position contains a non-finite active value")
    counts: dict[str, int] = {}
    known_codes: set[int] = set()
    for name, codes in type_codes.items():
        known_codes.update(codes)
        counts[name] = int((valid & np.isin(types, codes)).sum())
    counts["unknown"] = int((valid & ~np.isin(types, list(known_codes))).sum())
    if manifest.get("require_fluid", True) and counts["fluid"] == 0:
        raise RendererError("a saved frame contains no active native fluid points")
    frame_index = int(manifest.get("_active_frame_index", -1))
    time = float(manifest.get("_active_time_s", float("nan")))
    row: dict[str, Any] = {
        "frame": frame_index,
        "actual_time_s": time,
        "active": int(valid.sum()),
        "missing": int((~valid).sum()),
        "finite_positions_active": bool(finite_positions),
        "finite_fields": finite_fields,
        "type_counts_active": counts,
        "fluid_points": counts["fluid"],
        "moving_points": counts["moving"],
        "floating_points": counts["floating"],
        "identity_axis_preserved": True,
    }
    active_bounds = _bounds_from_points(points, valid)
    if active_bounds is not None:
        row["active_bounds"] = [list(pair) for pair in active_bounds]
    return row, identity


def _write_contact_sheet(
    output_dir: Path,
    sheet_index: int,
    tiles: Sequence[Any],
    frame_indices: Sequence[int],
    actual_times: Sequence[float],
) -> Path:
    from PIL import Image, ImageDraw

    columns, rows = 4, 6
    tile_width, tile_height = 384, 168
    sheet = Image.new("RGB", (columns * tile_width, rows * tile_height), "white")
    draw = ImageDraw.Draw(sheet)
    for index, tile in enumerate(tiles):
        x, y = (index % columns) * tile_width, (index // columns) * tile_height
        sheet.paste(tile, (x, y))
        frame = frame_indices[index]
        draw.text((x + 4, y + 144), f"frame {frame:04d}  t={actual_times[frame]:.9g}", fill="black")
    path = output_dir / f"all_frames_{sheet_index:03d}.png"
    sheet.save(path)
    return path


def _prepare_output(output_dir: Path) -> Path:
    frames_dir = output_dir / "frames"
    if frames_dir.exists():
        raise RendererError(f"refusing to reuse existing frame directory: {frames_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    frames_dir.mkdir()
    return frames_dir


def render_case(manifest_path: Path, output_dir: Path, diagnostic_frames: str | None = None) -> dict[str, Any]:
    """Render one immutable temporal product; root owns actual invocation."""

    # These imports are intentionally local: ordinary API checks do not need a
    # ParaView ABI, and no HDF5 reader is loaded into pvpython.
    import numpy as np
    from PIL import Image, ImageDraw
    from paraview import servermanager
    from paraview.simple import (
        GetAnimationScene,
        GetParaViewVersion,
        Render,
        SaveScreenshot,
        SaveState,
        XDMFReader,
    )
    from paraview.vtk.util.numpy_support import vtk_to_numpy

    manifest = load_manifest(manifest_path)
    actual_times_expected = np.asarray(manifest["actual_time_s"], dtype=np.float64)
    selection = parse_frame_selection(diagnostic_frames, len(actual_times_expected))
    frames_dir = _prepare_output(output_dir)
    source = Path(manifest["xdmf"])
    reader = XDMFReader(FileNames=[str(source)])
    reader.UpdatePipelineInformation()
    if str(reader.GetXMLName()) != "XdmfReader":
        raise RendererError(f"unexpected ParaView reader XML name: {reader.GetXMLName()}")
    actual_times = np.asarray(list(reader.TimestepValues), dtype=np.float64)
    np.testing.assert_array_equal(actual_times, actual_times_expected)
    try:
        reader.PointArrayStatus = list(reader.PointArrayStatus.Available)
        available_fields = set(reader.PointArrayStatus.Available)
    except AttributeError:
        available_fields = set(reader.PointArrayStatus)
    required_reader_fields = set(REQUIRED_POINT_FIELDS)
    missing_reader_fields = sorted(required_reader_fields - available_fields)
    if missing_reader_fields:
        raise RendererError(f"ParaView reader is missing point fields: {', '.join(missing_reader_fields)}")

    scene = GetAnimationScene()
    scene.UpdateAnimationUsingDataTimeSteps()
    if hasattr(scene, "PlayMode"):
        scene.PlayMode = "Snap To TimeSteps"
    manifest_for_run = dict(manifest)
    provided_bounds = manifest.get("camera_bounds", manifest.get("domain_bounds"))
    if provided_bounds is not None:
        bounds = _normalise_bounds(provided_bounds, "camera bounds")
        bounds_source = "manifest"
    else:
        scan_times = actual_times.tolist() if diagnostic_frames is None else actual_times[selection].tolist()
        bounds = _scan_native_bounds(reader, scan_times, servermanager, vtk_to_numpy)
        bounds_source = "native valid positions scanned through XdmfReader"
    camera = camera_for_bounds(bounds)
    pipeline = _build_display_pipeline(reader, manifest_for_run, camera)

    rows: list[dict[str, Any]] = []
    identity: dict[str, Any] | None = None
    contact_tiles: list[Any] = []
    contact_frames: list[int] = []
    contact_sheet_paths: list[str] = []
    gif_frames: list[Any] = []
    type_codes = resolve_type_codes(manifest)
    for selection_index, frame in enumerate(selection):
        time = float(actual_times[frame])
        scene.AnimationTime = time
        reader.UpdatePipeline(time=time)
        data = _fetch_dataset(reader, servermanager)
        manifest_for_run["_active_frame_index"] = frame
        manifest_for_run["_active_time_s"] = time
        row, identity = _frame_diagnostics(data, manifest_for_run, type_codes, identity, vtk_to_numpy, np)
        if identity["baseline_frame"] is None:
            identity["baseline_frame"] = frame
        rows.append(row)
        for view in pipeline["views"]:
            view.ViewTime = time
            pipeline["fluid"].UpdatePipeline(time=time)
            pipeline["moving"].UpdatePipeline(time=time)
            pipeline["floating"].UpdatePipeline(time=time)
            pipeline["boundary_outline"].UpdatePipeline(time=time)
            Render(view)
        png = frames_dir / f"frame_{frame:04d}.png"
        SaveScreenshot(str(png), pipeline["layout"], ImageResolution=[1280, 480])
        with Image.open(png) as picture:
            annotated = picture.convert("RGB")
        label = str(manifest.get("physical_case_id", manifest.get("case_id", "DS02")))
        review_label = "DIAGNOSTIC ONLY" if diagnostic_frames is not None else "VISUAL REVIEW PENDING ROOT"
        ImageDraw.Draw(annotated).text(
            (12, 12),
            f"{label} | frame {frame:04d}/{len(actual_times) - 1} | actual t={time:.9g} s | {review_label} | PRECISION NOT ACCEPTED",
            fill=(20, 20, 20),
        )
        annotated.save(png)
        tile = annotated.copy()
        tile.thumbnail((384, 144))
        contact_tiles.append(tile)
        contact_frames.append(frame)
        animation = annotated.copy()
        animation.thumbnail((768, 288))
        gif_frames.append(animation.convert("P", palette=Image.Palette.ADAPTIVE))
        if len(contact_tiles) == 24 or selection_index == len(selection) - 1:
            contact_sheet_paths.append(str(_write_contact_sheet(output_dir, len(contact_sheet_paths), contact_tiles, contact_frames, actual_times.tolist())))
            contact_tiles = []
            contact_frames = []

    # Save a state with the native temporal reader and display filters intact.
    scene.AnimationTime = float(actual_times[0])
    reader.UpdatePipeline(time=float(actual_times[0]))
    SaveState(str(output_dir / "case.pvsm"))
    gif_path = output_dir / "full_saved_animation.gif"
    gif_frames[0].save(gif_path, save_all=True, append_images=gif_frames[1:], duration=40, loop=0, optimize=False)

    report = {
        "schema": REPORT_SCHEMA,
        "renderer_revision": "f2-root-followup-052-stage1-visual-batch-renderer-v1",
        "paraview_version": str(GetParaViewVersion()),
        "input_manifest": str(manifest_path),
        "manifest_sha256": sha256(manifest_path),
        "xdmf": str(source),
        "xdmf_sha256_before": manifest["xdmf_sha256"],
        "xdmf_sha256_after": sha256(source),
        "source_h5_sha256": manifest.get("source_h5_sha256"),
        "source_h5_read_only": True,
        "frames": len(rows),
        "source_frames": len(actual_times),
        "all_frames_rendered": selection == list(range(len(actual_times))),
        "frame_selection": selection,
        "diagnostic_only": diagnostic_frames is not None,
        "actual_times_preserved_exactly": True,
        "native_identity_axis_preserved": True,
        "identity_baseline_frame": identity["baseline_frame"] if identity is not None else None,
        "nonfinite_active_states": 0,
        "frame_diagnostics": rows,
        "type_aliases": {name: list(codes) for name, codes in type_codes.items()},
        "camera": {**camera, "bounds_source": bounds_source},
        "boundary_display": {
            "filter": "display-only Clip plane",
            "plane_normal": [0.0, 1.0, 0.0],
            "plane_y": camera["cutaway_y"],
            "source_reader_unclipped": True,
            "keep_side": manifest.get("cutaway_keep_side", "positive"),
        },
        "rendering": "CPU software/offscreen; native fluid blue points, moving type-1 orange points, floating type-2 red points, fixed-boundary cutaway outline; full source fields remain in XMF/PVSM",
        "outputs": {
            "frames_dir": str(frames_dir),
            "contact_sheets": contact_sheet_paths,
            "gif": str(gif_path),
            "pvsm": str(output_dir / "case.pvsm"),
        },
        "visual_review": "pending root inspection of the full animation and every contact sheet",
        "numerical_precision_status": "not accepted",
        "independent_case_increment": 0,
        "coordinate_frame": manifest.get("coordinate_frame", "source_native_coordinates"),
        "animation_playback": "40ms per original saved frame; actual simulation time annotated; playback speed differs from physical time",
        "unknown_exclusions": manifest.get("unknown_exclusions", manifest.get("excluded_uid", "retained from source manifest without inference")),
    }
    if report["xdmf_sha256_after"] != report["xdmf_sha256_before"]:
        raise RendererError("XDMF source changed during rendering")
    (output_dir / "paraview-full-animation-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True, help="immutable temporal XDMF manifest")
    parser.add_argument("--output-dir", type=Path, required=True, help="new output directory")
    parser.add_argument("--diagnostic-frames", default=None, help="comma-separated frame indices for a bounded root diagnostic")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    report = render_case(args.manifest, args.output_dir, args.diagnostic_frames)
    print(json.dumps({
        "all_frames_rendered": report["all_frames_rendered"],
        "frames": report["frames"],
        "visual_review": report["visual_review"],
        "numerical_precision_status": report["numerical_precision_status"],
    }, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
