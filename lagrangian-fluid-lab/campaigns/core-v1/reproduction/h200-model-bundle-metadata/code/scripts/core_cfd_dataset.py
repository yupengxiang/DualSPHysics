"""Adapt registered CFD production records to the Core dataset contract.

The CFD preparation/evidence manifests describe how a case was produced.  The
ML reader needs a smaller, explicit record containing one immutable trajectory,
its split identity, and causal known inputs.  This module is the boundary
between those two schemas.  It never reads a reference trajectory to build
known inputs and it maps qualification records to the separate
``qualification`` split, which the trainer cannot consume.

The adapter accepts either the compact ``core.cfd.dataset.v1`` form below or
the existing F1/F4 design/production records when each case has a trajectory
and a prepared record attached (inline or through ``prepared``).  Static
qualification designs without HDF5 products are rejected with an actionable
error; they are design registrations, not trainable data.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import numpy as np

from scripts.core_contract import (FiniteGeometry, KnownInputs, PrescribedControl,
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


def _box_triangles(bounds, faces, *, component, body, triangles, components, bodies):
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
            # Keep an outward-facing winding for finite wall diagnostics.
            normal = np.cross(triangle[1] - triangle[0], triangle[2] - triangle[0])
            outward = 1 if side == 0 else -1
            if normal[axis] * outward < 0:
                triangle = triangle[[0, 2, 1]]
            triangles.append(triangle)
            components.append(component)
            bodies.append(body)


def geometry_from_cfd_config(config, *, coordinate_frame=COORDINATE_FRAME):
    """Build finite container/obstacle triangles from a prepared CFD config."""
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
                       triangles=triangles, components=components, bodies=bodies)
    array = np.asarray(triangles, dtype=float).reshape(-1, 3, 3)
    return FiniteGeometry(array, np.asarray(components, dtype=np.int64),
                          np.asarray(bodies, dtype=np.int64),
                          np.zeros((len(array), 3), dtype=float), coordinate_frame)


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
                                 coordinate_frame=COORDINATE_FRAME):
    """Create causal known inputs from immutable CFD preparation metadata."""
    if config.get("known_inputs") is not None:
        return known_inputs_from_dict(config["known_inputs"])
    coordinate_frame = config.get("coordinate_frame", coordinate_frame)
    geometry = geometry_from_cfd_config(config, coordinate_frame=coordinate_frame)
    gravity = np.asarray(config.get("gravity_m_s2", config.get("gravity_mps2", [0., 0., -9.81])),
                         dtype=float)
    if gravity.shape != (3,) or not np.isfinite(gravity).all():
        raise ValueError("CFD gravity must be a finite 3-vector")
    # CFD F1/F4 cases have prescribed gravity and no rigid-body forcing.  The
    # two-row schedule is explicit metadata, not sampled from a trajectory.
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


def _split(row, config, *, source_schema):
    if row.get("qualification_only") or config.get("qualification_claim") not in (None, "none"):
        return "qualification"
    value = row.get("split", config.get("split"))
    if value in ("qualification", "qualification_only"):
        return "qualification"
    if value in SPLITS:
        return value
    # A static F1 qualification design is deliberately never promoted by
    # successful parsing.  Production F4 records must declare their split.
    if "qualification" in source_schema or config.get("stage") == "qualification":
        return "qualification"
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
        if family not in {"F1", "F4"}:
            raise ValueError(f"CFD case {case_id} requires family F1 or F4")
        split = _split(row, config, source_schema=schema)
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
        if not isinstance(declared_hash, str) or len(declared_hash) != 64:
            raise ValueError(f"CFD case {case_id} requires a declared HDF5 SHA-256")
        if observed_hash is not None and declared_hash != observed_hash:
            raise ValueError(f"CFD HDF5 hash mismatch: {case_id}")
        hdf5_hash = declared_hash
        if prepared is not None and row.get("known_inputs") is None and row.get("known_inputs_ref") is None:
            known = known_inputs_from_cfd_config(config, family=family,
                                                 scope_id=row.get("scope_id", config.get("scope_id")))
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
    """CoreDataset-compatible lazy reader for F1/F4 production trajectories."""

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
    """Open either native CoreDataset or an F1/F4 CFD source manifest."""
    payload, _ = _read_manifest(manifest)
    if payload.get("schema") in SOURCE_SCHEMAS and payload.get("schema") not in {DATASET_SCHEMA, COMPACT_SCHEMA}:
        return CoreCFDDataset(manifest, data_root, **kwargs)
    return CoreDataset(manifest, data_root, **kwargs)


__all__ = ["SCHEMA", "SOURCE_SCHEMAS", "CoreCFDDataset", "CFDDataset",
           "adapt_manifest", "geometry_from_cfd_config", "known_inputs_from_cfd_config",
           "open_dataset"]
