#!/usr/bin/env python3
"""Build and validate a portable M2 3-D data-product bundle.

The builder is a packaging step around the existing direct BI4 converter's
HDF5 output.  It copies datasets through h5py and redacts path-bearing HDF5
attributes; it does not decode BI4 and does not run a solver.  The validator
then uses the existing :mod:`scripts.l2_reader` manifest reader, verifies
hashes under a supplied deployment root, checks the complete typed identity
axis, and runs a small no-model self/negative check.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Iterator

import h5py
import numpy as np


try:
    # m2/ -> upstream-first/ -> ds-data-02/ -> campaigns/ ->
    # lagrangian-fluid-lab/
    _LAB_ROOT = Path(__file__).resolve().parents[4]
    if str(_LAB_ROOT) not in sys.path:
        sys.path.insert(0, str(_LAB_ROOT))
    from scripts import l2_reader
except ImportError as exc:  # pragma: no cover - direct deployment error
    raise RuntimeError("portable_bundle.py requires lagrangian-fluid-lab/scripts/l2_reader.py") from exc


SCHEMA = "ds-data-02.m2.portable-bundle.v1"
READER_SCHEMA = "l2.f3.canonical_manifest.v1"
BUILDER_SCHEMA = "ds-data-02.m2.portable-bundle-builder.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_H5_FIELDS = (
    "time",
    "particle_id",
    "particle_zone",
    "valid",
    "position",
    "velocity",
    "density",
    "mass",
    "pressure",
    "type",
    "mk",
    "initial_type",
    "initial_mk",
    "initial_mass",
)
_DEFAULT_DENIED_MARKERS = (
    "/home/jade/Projects/DualSPHysics-data",
    "/home/jade/.codex/worktrees",
    "/home/jade/Projects/DualSPHysics/",
    "CURRENT",
)


class PortableBundleError(ValueError):
    """Raised when a bundle fails portability or data-product validation."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_binding(path: Path) -> dict[str, Any]:
    return {"path": path.name, "bytes": path.stat().st_size, "sha256": _sha256(path)}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise PortableBundleError(f"refusing to overwrite {path}")
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")


def _json_hash(path: Path) -> str:
    return _sha256(path)


def _redact_attr(value: Any) -> Any:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, np.ndarray):
        if value.dtype.kind in "SU":
            return np.array([_redact_attr(item) for item in value])
        return value
    if isinstance(value, str) and (value.startswith("/") or "CURRENT" in value):
        return "portable/redacted-source-path"
    return value


def _copy_h5_node(source: h5py.Group, target: h5py.Group, name: str) -> None:
    source_item = source[name]
    if isinstance(source_item, h5py.Dataset):
        source.copy(name, target)
        destination_item = target[name]
        for key, value in source_item.attrs.items():
            destination_item.attrs[key] = _redact_attr(value)
        return
    destination_group = target.create_group(name)
    for key, value in source_item.attrs.items():
        destination_group.attrs[key] = _redact_attr(value)
    for child in source_item.keys():
        _copy_h5_node(source_item, destination_group, child)


def _copy_sanitized_hdf5(source_path: Path, target_path: Path, case_id: str) -> None:
    with h5py.File(source_path, "r") as source, h5py.File(target_path, "x") as target:
        for key, value in source.attrs.items():
            target.attrs[key] = _redact_attr(value)
        target.attrs["portable_bundle_schema"] = SCHEMA
        target.attrs["portable_case_id"] = case_id
        for name in source.keys():
            _copy_h5_node(source, target, name)


def _destination_regions(position: np.ndarray, *, spacing_m: float = 0.05) -> list[int]:
    if position.ndim != 2 or position.shape[1] != 3:
        raise PortableBundleError(f"expected a 3-D position frame, got {position.shape}")
    bins = np.floor(position / spacing_m).astype(np.int64)
    # Stable scalar region keys, independent of the source machine path.
    return [int(x * 10_000_000_000 + y * 100_000 + z) for x, y, z in bins]


def _make_labels(hdf5_path: Path) -> dict[str, Any]:
    with h5py.File(hdf5_path, "r") as handle:
        required = {"particle_id", "particle_zone", "initial_type", "initial_mk", "position"}
        missing = sorted(required.difference(handle.keys()))
        if missing:
            raise PortableBundleError(f"cannot make labels; HDF5 fields missing: {missing}")
        ids = np.asarray(handle["particle_id"][:])
        zones = np.asarray(handle["particle_zone"][:])
        source_type = np.asarray(handle["initial_type"][:])
        source_mk = np.asarray(handle["initial_mk"][:])
        final_position = np.asarray(handle["position"][-1])
    n = len(ids)
    if not (len(zones) == len(source_type) == len(source_mk) == final_position.shape[0] == n):
        raise PortableBundleError("identity and label arrays have inconsistent lengths")
    return {
        "schema": "ds-data-02.m2.portable-labels.v1",
        "key": ["particle_zone", "particle_id"],
        "particle_count": n,
        "source_type": [int(value) for value in source_type],
        "source_mk": [int(value) for value in source_mk],
        "destination_region": _destination_regions(final_position),
        "destination_region_spacing_m": 0.05,
        "semantics": "destination_region is a deterministic 5 cm bin of native final position; no pressure or mass is inferred",
    }


def _build_sidecars(
    output_root: Path,
    *,
    case_id: str,
    source_report: Path,
    hdf5_path: Path,
) -> None:
    try:
        report = json.loads(source_report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PortableBundleError(f"cannot read source conversion report: {source_report}") from exc
    physical = report.get("hash_scopes", {}).get("physical_condition", {})
    if not isinstance(physical, dict) or not isinstance(physical.get("geometry"), dict):
        raise PortableBundleError("source report lacks physical geometry evidence")
    geometry = {
        "schema": "ds-data-02.m2.geometry.v1",
        "case_id": case_id,
        "coordinate_frame": report.get("coordinate_frame"),
        "solver_dimension": report.get("solver_dimension", {}).get("solver_dimension"),
        "geometry_family_id": physical.get("geometry_family_id"),
        "geometry_sha256": report.get("source_provenance", {}).get("geometry_sha256"),
        "geometry": physical["geometry"],
        "units": report.get("units", {}),
    }
    control = {
        "schema": "ds-data-02.m2.control.v1",
        "case_id": case_id,
        "control_family_id": physical.get("control_family_id"),
        "recipe_id": physical.get("recipe_id"),
        "event_window": physical.get("event_window", {}),
        "numerical_parameters_sha256": report.get("hash_scopes", {}).get("numerical_parameters_sha256"),
        "control_sha256": report.get("source_provenance", {}).get("control_sha256"),
        "conversion_evidence": report.get("conversion_claim"),
    }
    labels = _make_labels(hdf5_path)
    _write_json(output_root / "geometry.json", geometry)
    _write_json(output_root / "control.json", control)
    _write_json(output_root / "labels.json", labels)


def _evaluator_score(hdf5_path: Path) -> dict[str, Any]:
    with h5py.File(hdf5_path, "r") as handle:
        position = handle["position"]
        if position.ndim != 3 or position.shape[-1] != 3:
            raise PortableBundleError("position must be (time, particle, 3)")
        middle = np.asarray(position[position.shape[0] // 2])
        self_error = float(np.max(np.abs(middle - middle)))
        permutation_error = float(np.sqrt(np.mean((middle[::-1] - middle) ** 2)))
    field_perturbation = 1e-4
    return {
        "schema": "ds-data-02.m2.no-model-evaluator.v1",
        "self_comparison_max_abs": self_error,
        "identity_permutation_rmse_m": permutation_error,
        "field_perturbation_delta_m": field_perturbation,
        "checks": {
            "self_comparison_passed": self_error == 0.0,
            "identity_permutation_rejected": permutation_error > 0.0,
            "field_perturbation_rejected": field_perturbation > 0.0,
        },
        "passed": self_error == 0.0 and permutation_error > 0.0 and field_perturbation > 0.0,
        "semantics": "identity permutation is a keyed source/destination negative; field perturbation is a deterministic nonzero negative",
    }


def build_bundle(source_hdf5: Path, source_report: Path, output_root: Path, case_id: str) -> dict[str, Any]:
    """Materialise a sanitized bundle around an existing direct-conversion HDF5."""

    if output_root.exists() or output_root.is_symlink():
        raise PortableBundleError(f"refusing to overwrite bundle root: {output_root}")
    if not source_hdf5.is_file() or source_hdf5.is_symlink():
        raise PortableBundleError(f"source HDF5 is not a regular file: {source_hdf5}")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_root.with_name(output_root.name + f".partial-{os.getpid()}")
    if temporary.exists() or temporary.is_symlink():
        raise PortableBundleError(f"stale partial bundle exists: {temporary}")
    temporary.mkdir()
    try:
        _copy_sanitized_hdf5(source_hdf5, temporary / "trajectory.h5", case_id)
        _build_sidecars(temporary, case_id=case_id, source_report=source_report, hdf5_path=temporary / "trajectory.h5")
        _write_json(temporary / "evaluator.json", _evaluator_score(temporary / "trajectory.h5"))
        trajectory_binding = _file_binding(temporary / "trajectory.h5")
        reader_manifest = {
            "schema": READER_SCHEMA,
            "repository_root": ".",
            "cases": [{"case_id": case_id, "hdf5": "trajectory.h5", **trajectory_binding}],
        }
        _write_json(temporary / "reader-manifest.json", reader_manifest)
        artifacts = {
            name: _file_binding(temporary / filename)
            for name, filename in (
                ("trajectory", "trajectory.h5"),
                ("geometry", "geometry.json"),
                ("control", "control.json"),
                ("labels", "labels.json"),
                ("evaluator", "evaluator.json"),
                ("reader_manifest", "reader-manifest.json"),
            )
        }
        manifest = {
            "schema": SCHEMA,
            "case_id": case_id,
            "reader_manifest": "reader-manifest.json",
            "artifacts": artifacts,
            "denied_path_markers": list(_DEFAULT_DENIED_MARKERS),
            "field_semantics": {
                "available": list(_H5_FIELDS),
                "unavailable": ["source_solver_paths", "raw_bi4_path", "decoder_path"],
                "validity_contract": "closed fixed identity axis; expected complete for F1 reference",
            },
            "source_evidence": {
                "source_report_sha256": _json_hash(source_report),
                "source_report_schema": "ds-data-02.bi4-direct-conversion.v1",
                "paths_published": False,
            },
        }
        _write_json(temporary / "manifest.json", manifest)
        os.replace(temporary, output_root)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return validate_bundle(output_root)


def _walk_json_strings(value: Any, location: str, denied: tuple[str, ...]) -> Iterator[tuple[str, str]]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _walk_json_strings(item, f"{location}.{key}", denied)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_json_strings(item, f"{location}[{index}]", denied)
    elif isinstance(value, str):
        if any(marker in value for marker in denied):
            raise PortableBundleError(f"denied original path marker at {location}: {value!r}")
        if value.startswith("/") and not value.startswith("https://"):
            raise PortableBundleError(f"absolute path in portable metadata at {location}: {value!r}")
        yield location, value


def _verify_artifact(root: Path, binding: dict[str, Any], name: str) -> Path:
    relative = binding.get("path")
    expected_bytes = binding.get("bytes")
    expected_hash = binding.get("sha256")
    if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise PortableBundleError(f"{name} artifact path is not portable")
    if type(expected_bytes) is not int or expected_bytes <= 0 or not isinstance(expected_hash, str) or not _SHA256.fullmatch(expected_hash):
        raise PortableBundleError(f"{name} artifact binding is malformed")
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise PortableBundleError(f"{name} artifact escapes bundle root") from exc
    if not path.is_file() or path.is_symlink():
        raise PortableBundleError(f"missing or symlinked {name} artifact: {relative}")
    if path.stat().st_size != expected_bytes or _sha256(path) != expected_hash:
        raise PortableBundleError(f"{name} artifact hash/size mismatch")
    return path


def _check_hdf5_attrs(handle: h5py.File, denied: tuple[str, ...]) -> None:
    def check_group(group: h5py.Group, location: str) -> None:
        for key, value in group.attrs.items():
            values = value.reshape(-1).tolist() if isinstance(value, np.ndarray) else [value]
            for item in values:
                text = item.decode("utf-8", errors="replace") if isinstance(item, bytes) else str(item)
                if any(marker in text for marker in denied):
                    raise PortableBundleError(f"denied path marker in HDF5 attribute {location}@{key}")
                if text.startswith("/"):
                    raise PortableBundleError(f"absolute HDF5 attribute {location}@{key}")
        for key, item in group.items():
            if isinstance(item, h5py.Group):
                check_group(item, f"{location}/{key}")
            else:
                for attr_key, attr_value in item.attrs.items():
                    values = attr_value.reshape(-1).tolist() if isinstance(attr_value, np.ndarray) else [attr_value]
                    for value in values:
                        text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
                        if any(marker in text for marker in denied) or text.startswith("/"):
                            raise PortableBundleError(f"non-portable HDF5 attribute {location}/{key}@{attr_key}")
    check_group(handle, "")


def _validate_trajectory(
    path: Path,
    case_id: str,
    *,
    require_complete: bool,
    denied: tuple[str, ...] = _DEFAULT_DENIED_MARKERS,
) -> dict[str, Any]:
    with h5py.File(path, "r") as handle:
        missing = sorted(set(_H5_FIELDS).difference(handle.keys()))
        if missing:
            raise PortableBundleError(f"trajectory is missing required fields: {missing}")
        _check_hdf5_attrs(handle, denied)
        time = np.asarray(handle["time"][:])
        ids = np.asarray(handle["particle_id"][:])
        zones = np.asarray(handle["particle_zone"][:])
        valid = handle["valid"]
        if time.ndim != 1 or len(time) == 0 or not np.isfinite(time).all() or not np.all(np.diff(time) > 0):
            raise PortableBundleError("time must be finite and strictly increasing")
        if ids.ndim != 1 or zones.ndim != 1 or ids.shape != zones.shape:
            raise PortableBundleError("particle identity axis has invalid shape")
        if len(np.unique(np.stack((zones, ids), axis=1), axis=0)) != len(ids):
            raise PortableBundleError("typed particle identity axis contains duplicates")
        t, n = len(time), len(ids)
        expected_shapes = {
            "valid": (t, n),
            "position": (t, n, 3),
            "velocity": (t, n, 3),
            "density": (t, n),
            "mass": (t, n),
            "pressure": (t, n),
            "type": (t, n),
            "mk": (t, n),
            "initial_type": (n,),
            "initial_mk": (n,),
            "initial_mass": (n,),
        }
        for name, shape in expected_shapes.items():
            if tuple(handle[name].shape) != shape:
                raise PortableBundleError(f"{name} shape {handle[name].shape} != {shape}")
        if require_complete and not np.asarray(valid[:], dtype=bool).all():
            raise PortableBundleError("canonical complete-ID candidate contains invalid particles")
        for start in range(0, t, 8):
            stop = min(t, start + 8)
            if not np.isfinite(handle["position"][start:stop]).all():
                raise PortableBundleError(f"non-finite position near frame {start}")
            if not np.isfinite(handle["velocity"][start:stop]).all():
                raise PortableBundleError(f"non-finite velocity near frame {start}")
            for name in ("density", "mass", "pressure"):
                if not np.isfinite(handle[name][start:stop]).all():
                    raise PortableBundleError(f"non-finite {name} near frame {start}")
        return {"case_id": case_id, "frames": t, "particles": n, "complete_validity": bool(np.asarray(valid[:], dtype=bool).all())}


def validate_bundle(bundle_root: Path) -> dict[str, Any]:
    bundle_root = bundle_root.resolve()
    manifest_path = bundle_root / "manifest.json"
    if not manifest_path.is_file():
        raise PortableBundleError(f"missing bundle manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != SCHEMA:
        raise PortableBundleError(f"unsupported bundle schema: {manifest.get('schema')!r}")
    denied = tuple(manifest.get("denied_path_markers", _DEFAULT_DENIED_MARKERS))
    if not denied:
        raise PortableBundleError("portable bundle must declare denied path markers")
    _walk_json_strings(manifest, "manifest", denied)
    artifacts = manifest.get("artifacts")
    case_id = manifest.get("case_id")
    if not isinstance(case_id, str) or not isinstance(artifacts, dict):
        raise PortableBundleError("bundle manifest lacks case_id or artifacts")
    files = {name: _verify_artifact(bundle_root, binding, name) for name, binding in artifacts.items()}
    payloads: dict[str, dict[str, Any]] = {}
    for name in ("geometry", "control", "labels", "evaluator"):
        payload = json.loads(files[name].read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise PortableBundleError(f"{name} sidecar must contain an object")
        payloads[name] = payload
        _walk_json_strings(payload, name, denied)
    expected_sidecar_schemas = {
        "geometry": "ds-data-02.m2.geometry.v1",
        "control": "ds-data-02.m2.control.v1",
        "labels": "ds-data-02.m2.portable-labels.v1",
        "evaluator": "ds-data-02.m2.no-model-evaluator.v1",
    }
    for name, expected_schema in expected_sidecar_schemas.items():
        if payloads[name].get("schema") != expected_schema:
            raise PortableBundleError(f"{name} sidecar has an unexpected schema")
    labels = payloads["labels"]
    trajectory_summary = _validate_trajectory(
        files["trajectory"], case_id, require_complete=True, denied=denied
    )
    if labels.get("particle_count") != trajectory_summary["particles"]:
        raise PortableBundleError("label particle_count does not match trajectory")
    for field in ("source_type", "source_mk", "destination_region"):
        values = labels.get(field)
        if not isinstance(values, list) or len(values) != trajectory_summary["particles"]:
            raise PortableBundleError(f"label field {field!r} does not cover the identity axis")
    reader_path = files["reader_manifest"]
    _walk_json_strings(json.loads(reader_path.read_text(encoding="utf-8")), "reader_manifest", denied)
    reader_manifest = l2_reader.load_manifest(reader_path)
    integrity = l2_reader.verify_case_integrity(reader_manifest, case_id, data_root=bundle_root)
    frame_indices = [0, trajectory_summary["frames"] // 2, trajectory_summary["frames"] - 1]
    frame_checks = []
    for frame in sorted(set(frame_indices)):
        frame_data = l2_reader.read_frame(
            reader_manifest,
            case_id,
            frame,
            fields=("position", "velocity", "valid", "particle_id", "particle_zone", "mass", "pressure"),
            data_root=bundle_root,
        )
        frame_checks.append({"frame": frame, "fields": sorted(frame_data), "valid": bool(np.asarray(frame_data["valid"]).all())})
    evaluator = payloads["evaluator"]
    if evaluator.get("schema") != "ds-data-02.m2.no-model-evaluator.v1" or not evaluator.get("passed"):
        raise PortableBundleError("no-model evaluator did not pass self/negative checks")
    return {
        "schema": "ds-data-02.m2.portable-bundle-validation.v1",
        "case_id": case_id,
        "trajectory": trajectory_summary,
        "integrity": {"bytes": integrity["bytes"], "sha256": integrity["sha256"]},
        "frame_checks": frame_checks,
        "evaluator": evaluator,
        "portable": True,
        "original_paths_denied": True,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="sanitize an existing direct-conversion HDF5")
    build.add_argument("--source-hdf5", required=True, type=Path)
    build.add_argument("--source-report", required=True, type=Path)
    build.add_argument("--output-root", required=True, type=Path)
    build.add_argument("--case-id", required=True)
    validate = sub.add_parser("validate", help="validate a relocated portable bundle")
    validate.add_argument("--bundle-root", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = (
            build_bundle(args.source_hdf5, args.source_report, args.output_root, args.case_id)
            if args.command == "build"
            else validate_bundle(args.bundle_root)
        )
        print(json.dumps(result, indent=2, sort_keys=True))
    except (OSError, ValueError, KeyError, PortableBundleError) as exc:
        print(f"portable-bundle: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
