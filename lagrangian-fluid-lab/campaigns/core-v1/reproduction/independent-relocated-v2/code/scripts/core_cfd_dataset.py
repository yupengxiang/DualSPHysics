"""Adapt registered CFD production records to the Core dataset contract.

The CFD preparation/evidence manifests describe how a case was produced.  The
ML reader needs a smaller, explicit record containing one immutable trajectory,
its split identity, and causal known inputs.  This module is the boundary
between those two schemas.  It never reads a reference trajectory to build
known inputs and it maps qualification records to the separate
``qualification`` split, which the trainer cannot consume.

The adapter accepts either the compact ``core.cfd.dataset.v1`` form below or
the existing F1/F2/F4 design/production records when each case has a trajectory
and a prepared record attached (inline or through ``prepared``).  Static
qualification designs without HDF5 products are rejected with an actionable
error; they are design registrations, not trainable data.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import numpy as np

from scripts.core_contract import (FiniteGeometry, KnownInputs, PrescribedControl,
                                   PrescribedGeometry,
                                   DUALSPHYSICS_MVROTFILE_ROTATION_VERSION,
                                   contract_hash)
from scripts.core_dataset import (COMPACT_SCHEMA, SCHEMA as DATASET_SCHEMA,
                                  CoreDataset, known_inputs_from_dict,
                                  sha256_file, validate_manifest)


SCHEMA = "core.cfd.dataset.v1"
SOURCE_SCHEMAS = {
    SCHEMA,
    "core.cfd.v1",
    "core.production_design.v1",
    "core.f1.qualification.v1",
    "core.f4.qualification.v1",
    "core.f2.static_hold.v1",
    "core.f2.dynamic.v1",
}
SPLITS = {"train", "validation", "test", "id_test", "ood_test", "qualification"}
COORDINATE_FRAME = "fixed tank computational coordinates"


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _read_manifest(manifest):
    if isinstance(manifest, (str, Path)):
        path = Path(manifest).expanduser().resolve()
        return json.loads(path.read_text()), path
    if not isinstance(manifest, dict):
        raise ValueError("CFD manifest must be a mapping or JSON path")
    return manifest, None


def _resolve_path(value, data_root, *, source_parent=None, must_exist=False):
    """Resolve a source path and return a portable path relative to data_root."""
    if not isinstance(value, (str, Path)):
        raise ValueError("CFD asset path must be a string")
    candidate = Path(value).expanduser()
    root = Path(data_root).expanduser().resolve()
    if candidate.is_absolute():
        target = candidate.resolve()
    else:
        target = (root / candidate).resolve()
        if not target.exists() and source_parent is not None:
            alternate = (Path(source_parent) / candidate).resolve()
            if alternate.exists():
                target = alternate
    try:
        relative = target.relative_to(root)
    except ValueError as error:
        raise ValueError(f"CFD asset escapes data_root: {value}") from error
    if must_exist and not target.is_file():
        raise FileNotFoundError(target)
    return str(relative), target


def _box_triangles(bounds, faces, *, component, body, triangles, components, bodies,
                   toward_fluid=True):
    low = np.array([bounds[k] for k in ("xmin", "ymin", "zmin")], dtype=float)
    high = np.array([bounds[k] for k in ("xmax", "ymax", "zmax")], dtype=float)
    if low.shape != (3,) or not np.isfinite(np.r_[low, high]).all() or np.any(high <= low):
        raise ValueError("invalid finite CFD box")
    axes = {"left": (0, 0), "right": (0, 1), "front": (1, 0),
            "back": (1, 1), "bottom": (2, 0), "top": (2, 1)}
    for name in faces:
        if name not in axes:
            raise ValueError(f"unknown finite face {name}")
        axis, side = axes[name]
        other = [index for index in range(3) if index != axis]
        vertices = []
        for u, v in ((0, 0), (1, 0), (1, 1), (0, 1)):
            point = low.copy()
            point[axis] = (low if side == 0 else high)[axis]
            point[other[0]] = (low if u == 0 else high)[other[0]]
            point[other[1]] = (low if v == 0 else high)[other[1]]
            vertices.append(point)
        for ids in ((0, 1, 2), (0, 2, 3)):
            triangle = np.array([vertices[index] for index in ids], dtype=float)
            # Container/cup faces point into the fluid cavity.  An obstacle's
            # fluid-facing normal is the opposite side of the same box face.
            normal = np.cross(triangle[1] - triangle[0], triangle[2] - triangle[0])
            desired = (1 if side == 0 else -1) if toward_fluid else (-1 if side == 0 else 1)
            if normal[axis] * desired < 0:
                triangle = triangle[[0, 2, 1]]
            triangles.append(triangle)
            components.append(component)
            bodies.append(body)


def geometry_from_cfd_config(config, *, coordinate_frame=COORDINATE_FRAME,
                             data_root=None, source_parent=None):
    """Build finite triangles from a prepared CFD config.

    F2 is represented by its actual finite cup, receiver and tray faces.  A
    dynamic F2 row additionally carries a declared rigid motion schedule and
    returns :class:`PrescribedGeometry`; it is never reduced to the static
    ``wall_bounds`` envelope.
    """
    if str(config.get("family", "")).upper() == "F2" or any(
            key in config for key in ("cup", "receiver", "tray")):
        return _f2_geometry_from_config(config, coordinate_frame=coordinate_frame,
                                        data_root=data_root, source_parent=source_parent)
    wall = config.get("wall_spec")
    if wall is None:
        bounds = config.get("wall_bounds")
        if not isinstance(bounds, dict):
            raise ValueError("CFD config requires wall_spec or wall_bounds")
        wall = {"container_interior": bounds,
                "closed_faces": config.get("closed_faces", ()),
                "open_faces": config.get("open_faces", ()), "obstacles": []}
    bounds = wall.get("container_interior")
    if not isinstance(bounds, dict):
        raise ValueError("CFD wall_spec requires container_interior")
    triangles, components, bodies = [], [], []
    closed = tuple(wall.get("closed_faces", ()))
    _box_triangles(bounds, closed, component=0, body=0,
                   triangles=triangles, components=components, bodies=bodies)
    for obstacle_index, obstacle in enumerate(wall.get("obstacles", ())):
        if not isinstance(obstacle, dict):
            raise ValueError("CFD obstacle must be a mapping")
        _box_triangles(obstacle, ("left", "right", "front", "back", "bottom", "top"),
                       component=obstacle_index + 1, body=obstacle_index + 1,
                       triangles=triangles, components=components, bodies=bodies,
                       toward_fluid=False)
    array = np.asarray(triangles, dtype=float).reshape(-1, 3, 3)
    return FiniteGeometry(array, np.asarray(components, dtype=np.int64),
                          np.asarray(bodies, dtype=np.int64),
                          np.zeros((len(array), 3), dtype=float), coordinate_frame)


def _f2_box_bounds(box, *, name):
    if not isinstance(box, dict):
        raise ValueError(f"F2 {name} geometry must be a mapping")
    if all(key in box for key in ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax")):
        return {key: float(box[key]) for key in ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax")}
    low, size = box.get("low"), box.get("size")
    if not isinstance(low, (list, tuple)) or not isinstance(size, (list, tuple)):
        raise ValueError(f"F2 {name} requires low/size or explicit bounds")
    if len(low) != 3 or len(size) != 3:
        raise ValueError(f"F2 {name} low/size must have three coordinates")
    low, size = np.asarray(low, dtype=float), np.asarray(size, dtype=float)
    if not np.isfinite(np.r_[low, size]).all() or np.any(size <= 0):
        raise ValueError(f"F2 {name} low/size must be finite and positive")
    high = low + size
    return {key: float(value) for key, value in zip(
        ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax"),
        (low[0], high[0], low[1], high[1], low[2], high[2]))}


def _f2_motion_block(config):
    """Return an explicit motion mapping, if this is a dynamic F2 row."""
    for key in ("prescribed_motion", "cup_motion", "motion_contract", "motion"):
        block = config.get(key)
        if block is not None:
            if not isinstance(block, dict):
                raise ValueError(f"F2 {key} must be a mapping")
            return dict(block)
    # Accept a flat manifest form so the public adapter can consume the
    # motion sidecar emitted by the CFD preparation worker.
    path = (config.get("motion_file") or config.get("motion_path") or
            config.get("motion_file_name"))
    if path is None:
        return None
    return {
        "path": path,
        "sha256": config.get("motion_sha256"),
        "axis_point": config.get("axis_point", config.get("rotation_axis_point")),
        "axis_direction": config.get("axis_direction", config.get("rotation_axis")),
        "axis_p1": config.get("axis_p1"), "axis_p2": config.get("axis_p2"),
        "angle_units": config.get("anglesunits", config.get("angle_units", "degrees")),
        "moving_body_id": config.get("moving_body_id", config.get("cup", {}).get("mkbound", 0)),
    }


def _motion_from_definition(config, *, data_root=None, source_parent=None):
    """Read motion metadata from an explicitly named source definition.

    This fallback is limited to the registered DualSPHysics ``mvrotfile``
    declaration.  It also accepts the immutable ``definition_audit`` block
    emitted by the F2 preparation worker.  The latter is needed when a repair
    record keeps the predecessor ``source_definition`` for provenance while
    the actual generated definition and motion sidecar live in
    ``definition_audit``.  It never opens a trajectory HDF5, and a dynamic
    row still fails unless both the motion file and the finite rotation axis
    are declared in that source definition.
    """
    audit = config.get("definition_audit")
    if not isinstance(audit, dict):
        audit = {}
    audited_motion = audit.get("motion_file") is not None
    # A preparation audit may point at the predecessor XML as
    # ``source_definition`` while ``definition`` is the XML actually passed
    # to GenCase.  Only the audited motion file is allowed to make this row
    # dynamic; a bare ``motion_file_name`` is insufficient because static
    # qualification records also carry that provenance field.
    definition = audit.get("definition") if audited_motion else None
    definition = definition or config.get("source_definition")
    if definition is None or data_root is None:
        return None
    try:
        _, path = _resolve_path(definition, data_root, source_parent=source_parent, must_exist=True)
        if audited_motion:
            definition_hash = audit.get("definition_sha256")
            if (not isinstance(definition_hash, str) or len(definition_hash) != 64
                    or definition_hash.lower() != sha256_file(path)):
                raise ValueError("audited F2 definition XML hash mismatch")
        root = ET.parse(path).getroot()
        motion = root.find(".//mvrotfile")
        if motion is None:
            return None
        file_node, p1, p2 = motion.find("file"), motion.find("axisp1"), motion.find("axisp2")
        if file_node is None or p1 is None or p2 is None or not file_node.get("name"):
            return None
        def point(node):
            try:
                value = [float(node.get(axis)) for axis in "xyz"]
            except (TypeError, ValueError):
                return None
            return value if np.isfinite(value).all() else None
        first, second = point(p1), point(p2)
        if first is None or second is None:
            return None
        xml_motion_path = (path.parent / file_node.get("name")).resolve()
        _, xml_motion_path = _resolve_path(
            str(xml_motion_path), data_root, source_parent=path.parent, must_exist=True)
        motion_path = audit.get("motion_file")
        if motion_path is None:
            motion_path = str(xml_motion_path)
        else:
            # Resolve and validate the audited sidecar here so a generated
            # definition cannot silently point at a different asset.  The
            # XML and audit may use different relative roots, so compare the
            # immutable bytes rather than requiring identical path strings.
            _, motion_target = _resolve_path(motion_path, data_root,
                                             source_parent=source_parent,
                                             must_exist=True)
            motion_hash = audit.get("motion_sha256")
            if (not isinstance(motion_hash, str) or len(motion_hash) != 64
                    or motion_hash.lower() != sha256_file(motion_target)):
                raise ValueError("audited F2 motion sidecar hash mismatch")
            if sha256_file(xml_motion_path) != sha256_file(motion_target):
                raise ValueError("audited F2 motion conflicts with XML mvrotfile")
            motion_path = str(motion_target)
        return {
            "path": motion_path,
            "sha256": audit.get("motion_sha256"),
            "axis_p1": first, "axis_p2": second,
            "angle_units": motion.get("anglesunits", "degrees"),
            "moving_body_id": int(config.get("cup", {}).get("mkbound", 0)),
        }
    except (OSError, ET.ParseError, ValueError) as error:
        # An audited dynamic record is an explicit public contract.  Do not
        # turn a broken definition/hash/path into a static geometry by
        # swallowing the error.  The optional predecessor fallback remains
        # permissive only for legacy rows without an audit motion asset.
        if audited_motion:
            raise ValueError(f"invalid audited F2 prescribed motion: {error}") from error
        return None


def _resolve_motion_path(motion, data_root, *, source_parent=None):
    path = motion.get("path", motion.get("motion_file"))
    if not isinstance(path, (str, Path)):
        raise ValueError("dynamic F2 requires prescribed_motion.path to a motion sidecar")
    if data_root is None:
        raise ValueError("dynamic F2 requires data_root to resolve its motion sidecar")
    return _resolve_path(path, data_root, source_parent=source_parent, must_exist=True)


def _read_motion_file(path, *, units="degrees"):
    if str(units).lower() not in {"degree", "degrees", "deg", "radian", "radians", "rad"}:
        raise ValueError("dynamic F2 motion angle units must be degrees or radians")
    rows = []
    for line_number, raw in enumerate(Path(path).read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in re.split(r"[;,\t ]+", line) if part.strip()]
        if len(parts) != 2:
            raise ValueError(f"invalid F2 motion row {path}:{line_number}")
        try:
            rows.append((float(parts[0]), float(parts[1])))
        except ValueError as error:
            # A named header is permitted, but arbitrary nonnumeric rows are
            # not silently discarded from a prescribed control asset.
            if not rows and line.lower().startswith(("time", "#time")):
                continue
            raise ValueError(f"invalid F2 motion row {path}:{line_number}") from error
    values = np.asarray(rows, dtype=float)
    if values.ndim != 2 or values.shape[0] < 2 or not np.isfinite(values).all():
        raise ValueError("dynamic F2 motion sidecar needs at least two finite samples")
    if np.any(np.diff(values[:, 0]) <= 0):
        raise ValueError("dynamic F2 motion times must increase strictly")
    angles = values[:, 1]
    if str(units).lower() in {"radian", "radians", "rad"}:
        angles = np.degrees(angles)
    return values[:, 0], angles


def _axis_from_motion(motion):
    point = motion.get("axis_point", motion.get("rotation_axis_point"))
    direction = motion.get("axis_direction", motion.get("rotation_axis"))
    if direction is None and motion.get("axis_p1") is not None and motion.get("axis_p2") is not None:
        if point is None:
            point = motion["axis_p1"]
        direction = (np.asarray(motion["axis_p2"], dtype=float)
                     - np.asarray(motion["axis_p1"], dtype=float)).tolist()
    if point is None or direction is None:
        raise ValueError("dynamic F2 requires axis_point and axis_direction (or axis_p1/axis_p2)")
    point, direction = np.asarray(point, dtype=float), np.asarray(direction, dtype=float)
    if point.shape != (3,) or direction.shape != (3,) or not np.isfinite(np.r_[point, direction]).all():
        raise ValueError("dynamic F2 rotation axis must contain finite 3-vectors")
    if np.linalg.norm(direction) <= 1e-15:
        raise ValueError("dynamic F2 rotation axis must be nonzero")
    return point, direction


def _f2_geometry_from_config(config, *, coordinate_frame=COORDINATE_FRAME,
                             data_root=None, source_parent=None):
    triangles, components, bodies = [], [], []
    catchment = config.get("catchment_wall_spec")
    if config.get("catchment") is not None and catchment is None:
        raise ValueError("F2 catchment requires explicit fluid-facing catchment_wall_spec")
    if catchment is not None:
        if not isinstance(catchment, dict) or set(catchment.get("closed_faces", ())) != {
                "left", "right", "front", "back"} or catchment.get("open_faces") != ["top"]:
            raise ValueError("F2 catchment must declare four finite side walls and an open top")
        catchment_bounds = _f2_box_bounds(catchment.get("container_interior"), name="catchment")
        floor = catchment.get("floor", {})
        floor_z = float(floor.get("fluid_facing_surface_z_m", float("nan")))
        if not np.isfinite(floor_z) or floor_z != catchment_bounds["zmin"]:
            raise ValueError("F2 catchment floor must match its fluid-facing lower bound")
    for component, (name, default_faces, default_body) in enumerate((
            ("cup", ("bottom", "left", "right", "front", "back"), 0),
            ("receiver", ("bottom", "left", "right", "front", "back"), 1),
            ("tray", ("bottom",), 2))):
        box = config.get(name)
        if box is None:
            raise ValueError(f"F2 config requires finite {name} geometry")
        bounds = _f2_box_bounds(box, name=name)
        faces = tuple(box.get("faces", box.get("closed_faces", default_faces)))
        body = int(box.get("mkbound", box.get("body_id", default_body)))
        if name == "tray" and catchment is not None:
            if faces != ("bottom",) or body != int(floor["material_mkbound"]):
                raise ValueError("F2 catchment must retain the declared tray floor material")
            # Only the explicitly declared fluid-facing plane is emitted.
            # A bottom-only GenCase shell is not a solid slab: box size alone
            # must never be used to invent a different upper surface.
            bounds = dict(bounds, zmin=floor_z, zmax=catchment_bounds["zmax"])
        _box_triangles(bounds, faces, component=component, body=body,
                       triangles=triangles, components=components, bodies=bodies)
    if catchment is not None:
        _box_triangles(catchment_bounds, catchment["closed_faces"], component=3,
                       body=int(catchment["mkbound"]), triangles=triangles,
                       components=components, bodies=bodies)
    base = FiniteGeometry(np.asarray(triangles, dtype=float).reshape(-1, 3, 3),
                          np.asarray(components, dtype=np.int64), np.asarray(bodies, dtype=np.int64),
                          np.zeros((len(triangles), 3), dtype=float), coordinate_frame)
    audited_motion = config.get("definition_audit")
    audited_motion = (isinstance(audited_motion, dict)
                      and audited_motion.get("motion_file") is not None)
    dynamic = bool(config.get("dynamic", False) or config.get("moving", False)
                   or audited_motion
                   or (str(config.get("stage", "")).lower() in {"dynamic", "production"}
                       and str(config.get("family", "F2")).upper() == "F2"))
    motion = _f2_motion_block(config)
    # A static qualification canary may point back to the original rotating
    # source definition for provenance.  Never infer motion from that source;
    # only an explicitly dynamic row may consume its declared mvrotfile.
    if motion is None and dynamic:
        motion = _motion_from_definition(config, data_root=data_root, source_parent=source_parent)
    if motion is None:
        if dynamic:
            raise ValueError("dynamic F2 requires a declared prescribed motion sidecar and rotation axis; "
                             "angle-only trajectory control is not a public input")
        return base
    if data_root is None:
        raise ValueError("dynamic F2 requires an explicit data_root for its declared motion sidecar")
    _, motion_path = _resolve_motion_path(motion, data_root, source_parent=source_parent)
    declared_hash = motion.get("sha256", motion.get("motion_sha256"))
    observed_hash = hashlib.sha256(motion_path.read_bytes()).hexdigest()
    if declared_hash is not None:
        if not isinstance(declared_hash, str) or len(declared_hash) != 64:
            raise ValueError("dynamic F2 motion SHA-256 declaration is invalid")
        if declared_hash.lower() != observed_hash:
            raise ValueError("dynamic F2 motion sidecar hash mismatch")
    times, angles = _read_motion_file(motion_path, units=motion.get("angle_units", motion.get("anglesunits", "degrees")))
    axis_point, axis_direction = _axis_from_motion(motion)
    moving_body = int(motion.get("moving_body_id", config.get("cup", {}).get("mkbound", 0)))
    geometry = PrescribedGeometry(
        base.triangles, base.component_id, base.body_id, base.wall_velocity, base.coordinate_frame,
        times, angles, axis_point, axis_direction, moving_body,
        motion_version=DUALSPHYSICS_MVROTFILE_ROTATION_VERSION,
        motion_sha256=observed_hash)
    return geometry


def _config_from_prepared(prepared):
    if not isinstance(prepared, dict):
        raise ValueError("prepared CFD record must be a mapping")
    config = prepared.get("config", prepared)
    if not isinstance(config, dict):
        raise ValueError("prepared CFD record has no config mapping")
    return config


def _load_prepared(row, data_root, *, source_parent=None):
    inline = row.get("prepared_record")
    if inline is None and isinstance(row.get("prepared"), dict):
        inline = row["prepared"]
    if inline is None and isinstance(row.get("config"), dict):
        inline = row
    if inline is not None:
        return inline
    reference = (row.get("prepared") or row.get("prepared_path") or
                 row.get("prepared_json") or row.get("source_prepared"))
    if reference is None:
        return None
    _, path = _resolve_path(reference, data_root, source_parent=source_parent, must_exist=True)
    return json.loads(path.read_text())


def _horizon(config):
    values = []
    for key in ("time_max_s", "time_horizon_s", "registered_window_s"):
        value = config.get(key)
        if isinstance(value, (int, float)):
            values.append(float(value))
    for block_name in ("event_window", "horizon"):
        block = config.get(block_name, {})
        if isinstance(block, dict):
            for key, value in block.items():
                if "time" in str(key) or "horizon" in str(key):
                    if isinstance(value, (int, float)):
                        values.append(float(value))
    values = [value for value in values if np.isfinite(value) and value > 0]
    return max(values + [10.0]) + 1e-6


def known_inputs_from_cfd_config(config, *, family, scope_id=None,
                                 coordinate_frame=COORDINATE_FRAME,
                                 data_root=None, source_parent=None):
    """Create causal known inputs from immutable CFD preparation metadata."""
    if config.get("known_inputs") is not None:
        return known_inputs_from_dict(config["known_inputs"])
    coordinate_frame = config.get("coordinate_frame", coordinate_frame)
    geometry = geometry_from_cfd_config(config, coordinate_frame=coordinate_frame,
                                        data_root=data_root, source_parent=source_parent)
    gravity = np.asarray(config.get("gravity_m_s2", config.get("gravity_mps2", [0., 0., -9.81])),
                         dtype=float)
    if gravity.shape != (3,) or not np.isfinite(gravity).all():
        raise ValueError("CFD gravity must be a finite 3-vector")
    # CFD cases have prescribed gravity.  The two-row schedule is explicit
    # metadata, not sampled from a trajectory.  F2 rigid motion lives in the
    # geometry contract, so it is intentionally not encoded as future fluid
    # control data here.
    control = PrescribedControl(np.array([
        [0., *gravity.tolist(), 0., 0., 0.],
        [_horizon(config), *gravity.tolist(), 0., 0., 0.],
    ], dtype=float))
    dp = config.get("dp_m", config.get("resolution_m"))
    if not isinstance(dp, (int, float)) or not np.isfinite(dp) or float(dp) <= 0:
        raise ValueError("CFD config requires positive dp_m/resolution_m")
    density = config.get("density_kg_m3", config.get("reference_density_kgm3", 1000.))
    if not isinstance(density, (int, float)) or not np.isfinite(density) or density <= 0:
        raise ValueError("CFD density must be positive and finite")
    numerics = {
        "dp_m": float(dp), "h_m": float(.91924 * np.sqrt(3.) * float(dp)),
        "recipe_id": str(config.get("recipe_id", config.get("recipe", "cfd"))),
        "native_velocity_correction": True,
    }
    physics = {
        "gravity_mps2": gravity.tolist(), "reference_density_kgm3": float(density),
        "family": str(family), "scope_id": str(scope_id or config.get("scope_id", "cfd")),
    }
    # Preserve only an explicitly declared physical kinematic viscosity.  The
    # solver's artificial ``Visco`` coefficient is a numerical treatment and
    # must never be exposed as material viscosity in the public contract.
    viscosity_declared = "physical_kinematic_viscosity_m2_s" in config
    formulation_declared = "viscosity_formulation" in config
    if formulation_declared and not viscosity_declared:
        raise ValueError(
            "viscosity_formulation requires physical_kinematic_viscosity_m2_s")
    if viscosity_declared:
        try:
            viscosity = float(config["physical_kinematic_viscosity_m2_s"])
        except (TypeError, ValueError) as error:
            raise ValueError(
                "physical kinematic viscosity must be finite and positive") from error
        if not np.isfinite(viscosity) or viscosity <= 0:
            raise ValueError("physical kinematic viscosity must be finite and positive")
        if config.get("viscosity_formulation") != "laminar":
            raise ValueError(
                "explicit physical viscosity requires laminar formulation")
        physics.update({
            "physical_kinematic_viscosity_m2_s": viscosity,
            "viscosity_formulation": "laminar",
            "viscosity_source": "declared_physical_kinematic_viscosity_m2_s",
        })
    if isinstance(geometry, PrescribedGeometry):
        physics["geometry_motion_semantics"] = "declared_f2_rotation_pose_and_wall_velocity"
        physics["geometry_motion_sha256"] = geometry.motion_sha256
    return KnownInputs(geometry, control, physics, numerics, coordinate_frame)


def _source_rows(payload):
    rows = payload.get("cases")
    if not isinstance(rows, list):
        rows = payload.get("cells")
    if not isinstance(rows, list):
        rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("CFD production manifest requires a nonempty cases/cells list")
    return rows


def _source_path(row):
    for key in ("hdf5", "trajectory", "trajectory_h5", "trajectory_path"):
        if row.get(key) is not None:
            return row[key]
    for key in ("product", "conversion", "result"):
        block = row.get(key)
        if isinstance(block, dict):
            for nested in ("hdf5", "trajectory", "trajectory_h5", "path"):
                if block.get(nested) is not None:
                    return block[nested]
    return None


def _split(row, config, *, source_schema, family=None):
    # The prepared physical lineage outranks a wrapper's requested split.
    # Repair/calibration derivatives cannot be relabelled for training or
    # model selection, including older canaries with an incorrect false flag.
    stage = str(config.get("stage", row.get("stage", ""))).lower()
    if (row.get("qualification_only") or config.get("qualification_only")
            or config.get("qualification_claim") not in (None, "none")
            or config.get("split") in ("qualification", "qualification_only")
            or "qualification" in source_schema
            or stage in {"qualification", "qualification_only", "canary", "repair_canary",
                         "calibration", "diagnostic", "repair", "qualification_canary"}):
        return "qualification"
    # The registered F2 static cup is a qualification-only canary.  Its
    # successful preparation must never become a train/validation row merely
    # because a source wrapper omitted qualification_only.
    if (str(family or config.get("family", "")).upper() == "F2"
            and ("static_cup_hold" in str(config.get("scope_id", "")).lower()
                 or (str(config.get("stage", "")).lower() == "canary"
                     and not config.get("dynamic", False)))):
        return "qualification"
    value = row.get("split", config.get("split"))
    if value in ("qualification", "qualification_only"):
        return "qualification"
    if value in SPLITS:
        return value
    raise ValueError(f"CFD case {row.get('case_id')} has no registered split")


def adapt_manifest(manifest, data_root, *, require_existing=True):
    """Return a validated ``core.dataset.v1`` manifest for CFD cases."""
    payload, source_path = _read_manifest(manifest)
    schema = payload.get("schema")
    if schema in {DATASET_SCHEMA, COMPACT_SCHEMA}:
        validate_manifest(payload)
        return payload
    if schema not in SOURCE_SCHEMAS:
        raise ValueError(f"unsupported CFD source manifest schema: {schema}")
    root = Path(data_root).expanduser().resolve()
    source_parent = source_path.parent if source_path is not None else None
    family_default = payload.get("family")
    result = {
        "schema": DATASET_SCHEMA,
        "dataset_id": payload.get("dataset_id", f"{schema}:core"),
        "formal_release": bool(payload.get("formal_release", False)),
        "source_schema": schema,
        "source_manifest_sha256": (sha256_file(source_path) if source_path is not None else _digest(payload)),
        "source_qualification_claim": payload.get("qualification_claim", "none"),
        "cases": [],
    }
    for index, original in enumerate(_source_rows(payload)):
        if not isinstance(original, dict):
            raise ValueError(f"CFD case {index} must be a mapping")
        row = copy.deepcopy(original)
        case_id = row.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError(f"CFD case {index} has no case_id")
        prepared = _load_prepared(row, root, source_parent=source_parent)
        config = _config_from_prepared(prepared) if prepared is not None else row
        family = str(row.get("family", config.get("family", family_default or "")))
        if family not in {"F1", "F2", "F4"}:
            raise ValueError(f"CFD case {case_id} requires family F1, F2 or F4")
        split = _split(row, config, source_schema=schema, family=family)
        source_hdf5 = _source_path(row)
        if source_hdf5 is None:
            raise ValueError(
                f"CFD case {case_id} has no trajectory HDF5; static qualification records "
                "cannot be used for training or evaluation")
        hdf5, path = _resolve_path(source_hdf5, root, source_parent=source_parent,
                                   must_exist=require_existing)
        observed_hash = sha256_file(path) if path.is_file() else None
        declared_hash = row.get("sha256") or row.get("hdf5_sha256")
        if isinstance(row.get("file"), dict):
            declared_hash = declared_hash or row["file"].get("sha256")
        for key in ("product", "conversion", "result"):
            block = row.get(key)
            if isinstance(block, dict):
                declared_hash = (declared_hash or block.get("sha256") or
                                 block.get("hdf5_sha256"))
        if not isinstance(declared_hash, str) or len(declared_hash) != 64:
            raise ValueError(f"CFD case {case_id} requires a declared HDF5 SHA-256")
        if observed_hash is not None and declared_hash != observed_hash:
            raise ValueError(f"CFD HDF5 hash mismatch: {case_id}")
        hdf5_hash = declared_hash
        if prepared is not None and row.get("known_inputs") is None and row.get("known_inputs_ref") is None:
            known = known_inputs_from_cfd_config(
                config, family=family,
                scope_id=row.get("scope_id", config.get("scope_id")),
                data_root=root, source_parent=source_parent)
        elif row.get("known_inputs") is not None:
            known = known_inputs_from_dict(row["known_inputs"])
        else:
            # Resolve a pre-existing compact input record when a production
            # manifest already carries one.  Its assets remain content-addressed
            # and are validated by CoreDataset.
            from scripts.core_dataset import known_inputs_from_record
            known = known_inputs_from_record(row, root)
        physical = str(row.get("physical_case_id", config.get("physical_case_id", case_id)))
        # F1 qualification tables intentionally reuse one physical lineage for
        # several resolution views.  Preserve that identity; CoreDataset
        # accepts same-split views and rejects any cross-split leakage.
        lineage = str(row.get("lineage_group_id", config.get("lineage_group_id", physical)))
        bytes_declared = row.get("bytes")
        if bytes_declared is None and isinstance(row.get("file"), dict):
            bytes_declared = row["file"].get("bytes")
        if bytes_declared is None and path.is_file():
            bytes_declared = path.stat().st_size
        record = {
            "case_id": case_id, "physical_case_id": physical,
            "lineage_group_id": lineage, "family": family, "split": split,
            "scope_id": row.get("scope_id", config.get("scope_id", family)),
            "hdf5": hdf5, "sha256": hdf5_hash, "bytes": bytes_declared,
            "known_inputs": known.as_dict(), "known_inputs_sha256": contract_hash(known),
            "qualification_case": split == "qualification",
            "evaluation_role": row.get("evaluation_role", "development"),
            "provenance": {"source_schema": schema,
                           "source_case_index": index,
                           "source_physical_case_id": row.get("physical_case_id", config.get("physical_case_id", case_id)),
                           "prepared": row.get("prepared", row.get("prepared_path")),
                           "stage": row.get("stage", config.get("stage"))},
        }
        result["cases"].append(record)
    validate_manifest(result)
    return result


class CoreCFDDataset:
    """CoreDataset-compatible lazy reader for F1/F2/F4 trajectories."""

    def __init__(self, manifest, data_root=None, *, max_open_files=4, require_existing=True):
        if data_root is None and isinstance(manifest, (str, Path)):
            data_root = Path(manifest).expanduser().resolve().parent
        if data_root is None:
            raise ValueError("CFD dataset requires explicit data_root")
        self.data_root = Path(data_root).expanduser().resolve()
        self.source_manifest, self.source_path = _read_manifest(manifest)
        self.canonical_manifest = adapt_manifest(self.source_manifest, self.data_root,
                                                 require_existing=require_existing)
        self._dataset = CoreDataset(self.canonical_manifest, self.data_root,
                                    max_open_files=max_open_files)
        self.manifest = self._dataset.manifest
        self.manifest_sha256 = self._dataset.manifest_sha256

    def __getattr__(self, name):
        return getattr(self._dataset, name)

    def __enter__(self):
        self._dataset.__enter__()
        return self

    def __exit__(self, *args):
        return self._dataset.__exit__(*args)


# Short alias for callers that use the source family name.
CFDDataset = CoreCFDDataset


def open_dataset(manifest, data_root=None, **kwargs):
    """Open either native CoreDataset or an F1/F2/F4 CFD source manifest."""
    payload, _ = _read_manifest(manifest)
    if payload.get("schema") in SOURCE_SCHEMAS and payload.get("schema") not in {DATASET_SCHEMA, COMPACT_SCHEMA}:
        return CoreCFDDataset(manifest, data_root, **kwargs)
    return CoreDataset(manifest, data_root, **kwargs)


__all__ = ["SCHEMA", "SOURCE_SCHEMAS", "CoreCFDDataset", "CFDDataset",
           "adapt_manifest", "geometry_from_cfd_config", "known_inputs_from_cfd_config",
           "open_dataset"]
