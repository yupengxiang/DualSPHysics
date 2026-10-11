#!/usr/bin/env python3
"""Package and verify an already-normalized M4 upstream data product.

The native BI4/PartOut conversion is owned by ``m2/upstream_conversion`` and
the data-product producer.  This module deliberately consumes only that
producer's normalized HDF5 plus its JSON interface.  It never decodes native
frames and never reconstructs a trajectory from raw payloads.

The validator is validity-aware: a non-finite value is permitted only on an
invalid numerical node, while every value used by a valid node or endpoint
must be finite.  A missing endpoint is represented by ``unknown`` or
``censored`` and is never assigned a physical fate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Any, Iterable, Mapping

import h5py
import numpy as np


INTERFACE_SCHEMA = "ds-data-02.m4.native-conversion-interface.v1"
BUNDLE_SCHEMA = "ds-data-02.m4.portable-bundle.v1"
ENDPOINT_SCHEMA = "ds-data-02.m4.endpoint-transport.v1"
VALIDATION_SCHEMA = "ds-data-02.m4.portable-validation.v1"
EVALUATOR_SCHEMA = "ds-data-02.m4.no-model-evaluator.v1"

SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
CASE_RE = re.compile(r"^UF_F1_MDBC_[A-Z0-9_]+$", re.ASCII)

REQUIRED_ROOT_FIELDS = (
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
FRAME_FIELDS = ("position", "velocity", "density", "mass", "pressure", "type", "mk")
INITIAL_FIELDS = ("initial_type", "initial_mk", "initial_mass")
ALLOWED_SOURCE_LABELS = frozenset(("valid_source", "unknown", "censored"))
ALLOWED_DESTINATION_LABELS = frozenset(("valid_destination", "unknown", "censored"))
MISSING_LABELS = frozenset(("unknown", "censored"))
FORBIDDEN_FATE_LABELS = frozenset(
    ("lost", "escaped", "deposited", "impact", "boundary", "fluid", "solid", "outflow")
)


class M4Error(ValueError):
    """Raised when a normalized M4 interface or bundle is unsafe to use."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_array(values: np.ndarray, *, dtype: str | None = None) -> str:
    array = np.asarray(values, dtype=dtype) if dtype is not None else np.asarray(values)
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise M4Error(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")


def _file_binding(path: Path, *, relative_path: str | None = None) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise M4Error(f"artifact is not a regular file: {path}")
    return {"path": relative_path or path.name, "bytes": path.stat().st_size, "sha256": _sha256(path)}


def _valid_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise M4Error(f"{label} is not a lowercase SHA-256 digest")
    return value


def _relative_local(root: Path, value: Any, label: str, *, must_exist: bool = True) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise M4Error(f"{label} must be a relative package path")
    candidate = (root / value).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise M4Error(f"{label} escapes the interface directory")
    if must_exist and (candidate.is_symlink() or not candidate.is_file()):
        raise M4Error(f"{label} is not a regular file: {candidate}")
    return candidate


def _dataset(handle: h5py.File, name: str, label: str) -> h5py.Dataset:
    if not isinstance(name, str) or not name.startswith("/"):
        raise M4Error(f"{label} must be an absolute HDF5 dataset path")
    try:
        item = handle[name]
    except KeyError as exc:
        raise M4Error(f"missing {label} dataset {name}") from exc
    if not isinstance(item, h5py.Dataset):
        raise M4Error(f"{label} is not a dataset: {name}")
    return item


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="strict")
    if isinstance(value, np.bytes_):
        return bytes(value).decode("utf-8", errors="strict")
    return str(value)


def _labels(dataset: h5py.Dataset, label: str) -> list[str]:
    values = np.asarray(dataset[:])
    if values.ndim != 1:
        raise M4Error(f"{label} must be a one-dimensional string dataset")
    result: list[str] = []
    for index, value in enumerate(values):
        try:
            text = _text(value)
        except UnicodeError as exc:
            raise M4Error(f"{label}[{index}] is not UTF-8") from exc
        if text in FORBIDDEN_FATE_LABELS:
            raise M4Error(f"{label}[{index}] fabricates physical fate: {text!r}")
        result.append(text)
    return result


def _binary_mask(dataset: h5py.Dataset, label: str, shape: tuple[int, ...]) -> np.ndarray:
    values = np.asarray(dataset[:])
    if values.shape != shape:
        raise M4Error(f"{label} shape {values.shape} != {shape}")
    if values.dtype.kind not in "biu":
        raise M4Error(f"{label} must be boolean or integer-valued")
    result = values.astype(bool)
    if np.any(values != result):
        raise M4Error(f"{label} contains values other than zero or one")
    return result


def _finite_where_valid(values: np.ndarray, valid: np.ndarray, label: str) -> None:
    if values.shape[:2] != valid.shape:
        raise M4Error(f"{label} shape {values.shape} is incompatible with valid {valid.shape}")
    if values.ndim == 3:
        finite = np.isfinite(values).all(axis=2)
    elif values.ndim == 2:
        finite = np.isfinite(values)
    else:
        raise M4Error(f"{label} must be a two- or three-dimensional frame field")
    bad = valid & ~finite
    if np.any(bad):
        frame, particle = np.argwhere(bad)[0]
        raise M4Error(f"{label} has a non-finite valid value at frame {frame}, particle {particle}")


def _binding_from_manifest(root: Path, value: Any, label: str) -> tuple[Path, dict[str, Any]]:
    if not isinstance(value, Mapping):
        raise M4Error(f"{label} must be an object binding")
    path = _relative_local(root, value.get("path"), label)
    expected_bytes = value.get("bytes")
    if type(expected_bytes) is not int or expected_bytes < 0:
        raise M4Error(f"{label}.bytes is invalid")
    expected_hash = _valid_sha(value.get("sha256"), f"{label}.sha256")
    actual = _file_binding(path)
    if actual["bytes"] != expected_bytes or actual["sha256"] != expected_hash:
        raise M4Error(f"{label} does not match its file")
    return path, actual


def _validate_interface_shape(payload: Mapping[str, Any], *, allow_pending: bool) -> dict[str, Any]:
    if payload.get("schema") != INTERFACE_SCHEMA:
        raise M4Error(f"unsupported native conversion interface: {payload.get('schema')!r}")
    case_id = payload.get("case_id")
    if not isinstance(case_id, str) or not CASE_RE.fullmatch(case_id):
        raise M4Error("interface case_id is outside the F1 upstream contract")
    if payload.get("family_id") != "F1":
        raise M4Error("M4 interface is currently bounded to family F1")
    if payload.get("credit_status") != "not_credited":
        raise M4Error("prepared M4 inputs must remain explicitly not_credited")
    if payload.get("physical_fate_inferred") is not False:
        raise M4Error("M4 interface must explicitly forbid physical-fate inference")
    status = payload.get("status")
    if status not in ("normalized_verified", "template_pending_native_audit"):
        raise M4Error(f"unsupported interface status: {status!r}")
    hdf5_binding = payload.get("normalized_hdf5")
    if not isinstance(hdf5_binding, Mapping):
        raise M4Error("interface lacks normalized_hdf5 binding")
    _valid_sha(hdf5_binding.get("sha256"), "normalized_hdf5.sha256")
    if type(hdf5_binding.get("bytes")) is not int or hdf5_binding["bytes"] <= 0:
        raise M4Error("normalized_hdf5.bytes is invalid")
    identity = payload.get("identity_axis")
    if not isinstance(identity, Mapping):
        raise M4Error("interface lacks identity_axis")
    if identity.get("key") != "(Zone,Idp)":
        raise M4Error("identity axis must be keyed by (Zone,Idp)")
    if identity.get("full_initial_identity") is not True or identity.get("all_frames_fixed_axis") is not True:
        raise M4Error("interface must declare the full initial identity on every frame")
    count = identity.get("initial_particle_count")
    frame_count = identity.get("frame_count")
    if status == "normalized_verified":
        if type(count) is not int or count <= 0 or type(frame_count) is not int or frame_count <= 0:
            raise M4Error("verified interface needs positive initial and frame counts")
        _valid_sha(identity.get("initial_ids_sha256"), "identity_axis.initial_ids_sha256")
    elif not allow_pending:
        raise M4Error("native audit is pending; this interface is not a complete M4 product")
    elif count is not None and (type(count) is not int or count < 0):
        raise M4Error("pending interface initial_particle_count is invalid")
    exclusions = payload.get("exclusion_mask")
    if not isinstance(exclusions, Mapping):
        raise M4Error("interface lacks exclusion_mask")
    exclusion_status = exclusions.get("status")
    if exclusion_status == "verified":
        excluded_count = exclusions.get("count")
        if type(excluded_count) is not int or excluded_count < 0:
            raise M4Error("verified exclusion mask needs a non-negative count")
        _valid_sha(exclusions.get("ids_sha256"), "exclusion_mask.ids_sha256")
    elif exclusion_status == "pending_audit":
        if exclusions.get("count") is not None or exclusions.get("ids_sha256") is not None:
            raise M4Error("pending exclusion masks must leave count and hash unknown")
        if not allow_pending:
            raise M4Error("native exclusion mask is pending; no product acceptance is allowed")
    else:
        raise M4Error(f"unsupported exclusion mask status: {exclusion_status!r}")
    if exclusions.get("physical_fate_inferred") is not False:
        raise M4Error("exclusion mask must retain numerical censoring without physical fate")
    endpoints = payload.get("endpoint_transport")
    if not isinstance(endpoints, Mapping) or endpoints.get("schema") != ENDPOINT_SCHEMA:
        raise M4Error("interface lacks the M4 endpoint transport contract")
    if endpoints.get("source_frame") != 0 or endpoints.get("destination_frame") != "last":
        raise M4Error("endpoint transport must bind frame zero to the final frame")
    if endpoints.get("physical_fate_inferred") is not False:
        raise M4Error("endpoint transport must forbid physical-fate inference")
    required_endpoint_paths = (
        "particle_id_dataset",
        "particle_zone_dataset",
        "source_valid_dataset",
        "destination_valid_dataset",
        "source_label_dataset",
        "destination_label_dataset",
        "source_position_dataset",
        "destination_position_dataset",
        "displacement_dataset",
    )
    for key in required_endpoint_paths:
        value = endpoints.get(key)
        if not isinstance(value, str) or not value.startswith("/"):
            raise M4Error(f"endpoint transport field {key} must be an absolute HDF5 path")
    if set(endpoints.get("missing_endpoint_labels", [])) != MISSING_LABELS:
        raise M4Error("missing endpoint labels must be exactly unknown and censored")
    if endpoints.get("source_valid_label") != "valid_source" or endpoints.get("destination_valid_label") != "valid_destination":
        raise M4Error("endpoint valid labels are not bound to valid_source/valid_destination")
    receipts = payload.get("source_receipts")
    if not isinstance(receipts, list) or not receipts:
        raise M4Error("interface needs at least one source receipt")
    for index, receipt in enumerate(receipts):
        if not isinstance(receipt, Mapping):
            raise M4Error(f"source receipt {index} is not an object")
        _valid_sha(receipt.get("sha256"), f"source_receipts[{index}].sha256")
        if type(receipt.get("bytes")) is not int or receipt["bytes"] < 0:
            raise M4Error(f"source receipt {index} bytes is invalid")
    return {
        "case_id": case_id,
        "status": status,
        "identity_count": count,
        "frame_count": frame_count,
        "exclusion_status": exclusion_status,
        "exclusion_count": exclusions.get("count"),
    }


def load_interface(path: Path, *, allow_pending: bool = False) -> dict[str, Any]:
    """Load and structurally validate a data_product native conversion manifest."""

    if path.is_symlink() or not path.is_file():
        raise M4Error(f"interface is not a regular file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise M4Error(f"cannot read interface {path}") from exc
    if not isinstance(payload, dict):
        raise M4Error("native conversion interface must be a JSON object")
    _validate_interface_shape(payload, allow_pending=allow_pending)
    return payload


def _validate_hdf5(interface: Mapping[str, Any], hdf5_path: Path) -> dict[str, Any]:
    """Validate normalized HDF5 without opening any native/raw source."""

    endpoints = interface["endpoint_transport"]
    exclusions = interface["exclusion_mask"]
    expected_count = int(interface["identity_axis"]["initial_particle_count"])
    expected_frames = int(interface["identity_axis"]["frame_count"])
    with h5py.File(hdf5_path, "r") as handle:
        missing = sorted(set(REQUIRED_ROOT_FIELDS).difference(handle.keys()))
        if missing:
            raise M4Error(f"normalized HDF5 is missing required fields: {missing}")
        time = np.asarray(handle["time"][:])
        ids = np.asarray(handle["particle_id"][:])
        zones = np.asarray(handle["particle_zone"][:])
        valid = _binary_mask(handle["valid"], "valid", (len(time), len(ids)))
        if time.ndim != 1 or len(time) != expected_frames or len(time) == 0:
            raise M4Error("time does not match the interface frame count")
        if not np.isfinite(time).all() or not np.all(np.diff(time) > 0):
            raise M4Error("time must be finite and strictly increasing")
        if ids.ndim != 1 or zones.ndim != 1 or ids.shape != zones.shape or len(ids) != expected_count:
            raise M4Error("typed initial identity axis has the wrong shape")
        if ids.dtype.kind not in "iu" or zones.dtype.kind not in "iu":
            raise M4Error("particle identity fields must be integer-valued")
        if np.any(ids < 0) or np.any(zones < 0):
            raise M4Error("particle identity fields cannot be negative")
        typed = np.stack((zones.astype(np.int64), ids.astype(np.int64)), axis=1)
        if len(np.unique(typed, axis=0)) != len(ids):
            raise M4Error("typed initial identity axis contains duplicates")
        if _sha256_array(ids, dtype="<u4") != interface["identity_axis"]["initial_ids_sha256"]:
            raise M4Error("initial Idp identity hash disagrees with the interface")
        for name in FRAME_FIELDS:
            array = np.asarray(handle[name][:])
            expected_shape = (len(time), len(ids), 3) if name in ("position", "velocity") else (len(time), len(ids))
            if array.shape != expected_shape:
                raise M4Error(f"{name} shape {array.shape} != {expected_shape}")
            _finite_where_valid(array, valid, name)
        for name in INITIAL_FIELDS:
            array = np.asarray(handle[name][:])
            if array.shape != (len(ids),):
                raise M4Error(f"{name} shape {array.shape} != {(len(ids),)}")
            if not np.isfinite(array).all():
                raise M4Error(f"{name} contains a non-finite initial identity value")

        exclusion = _binary_mask(
            _dataset(handle, exclusions["mask_dataset"], "native exclusion mask"),
            "native exclusion mask",
            (len(ids),),
        )
        if exclusions["status"] != "verified":
            raise M4Error("a pending native exclusion mask cannot be packaged as an M4 product")
        if int(exclusion.sum()) != int(exclusions["count"]):
            raise M4Error("native exclusion count disagrees with the HDF5 mask")
        if _sha256_array(ids[exclusion], dtype="<u4") != exclusions["ids_sha256"]:
            raise M4Error("native exclusion Idp hash disagrees with the interface")
        if not np.array_equal(exclusion, ~valid[-1]):
            raise M4Error("native exclusion mask does not equal the final missing identity set")

        transport = {
            key: _dataset(handle, endpoints[key], key)
            for key in (
                "particle_id_dataset",
                "particle_zone_dataset",
                "source_valid_dataset",
                "destination_valid_dataset",
                "source_label_dataset",
                "destination_label_dataset",
                "source_position_dataset",
                "destination_position_dataset",
                "displacement_dataset",
            )
        }
        for key in ("particle_id_dataset", "particle_zone_dataset"):
            if tuple(transport[key].shape) != (len(ids),):
                raise M4Error(f"endpoint {key} has the wrong shape")
        endpoint_ids = np.asarray(transport["particle_id_dataset"][:])
        endpoint_zones = np.asarray(transport["particle_zone_dataset"][:])
        if not np.array_equal(endpoint_ids, ids) or not np.array_equal(endpoint_zones, zones):
            raise M4Error("endpoint identity labels changed the initial typed axis")
        source_valid = _binary_mask(transport["source_valid_dataset"], "source_valid", (len(ids),))
        destination_valid = _binary_mask(transport["destination_valid_dataset"], "destination_valid", (len(ids),))
        if not np.array_equal(source_valid, valid[0]) or not np.array_equal(destination_valid, valid[-1]):
            raise M4Error("endpoint validity masks disagree with frame validity")
        source_labels = _labels(transport["source_label_dataset"], "source_label")
        destination_labels = _labels(transport["destination_label_dataset"], "destination_label")
        if len(source_labels) != len(ids) or len(destination_labels) != len(ids):
            raise M4Error("endpoint label lengths do not match the identity axis")
        for index, (is_valid, label) in enumerate(zip(source_valid, source_labels)):
            if label not in ALLOWED_SOURCE_LABELS:
                raise M4Error(f"source_label[{index}] is outside the endpoint contract: {label!r}")
            expected = "valid_source" if is_valid else None
            if expected is not None and label != expected:
                raise M4Error(f"source_label[{index}] does not identify a valid source")
            if expected is None and label not in MISSING_LABELS:
                raise M4Error(f"source_label[{index}] fabricates a source fate")
        for index, (is_valid, label) in enumerate(zip(destination_valid, destination_labels)):
            if label not in ALLOWED_DESTINATION_LABELS:
                raise M4Error(f"destination_label[{index}] is outside the endpoint contract: {label!r}")
            expected = "valid_destination" if is_valid else None
            if expected is not None and label != expected:
                raise M4Error(f"destination_label[{index}] does not identify a valid destination")
            if expected is None and label not in MISSING_LABELS:
                raise M4Error(f"destination_label[{index}] fabricates a destination fate")
        source_position = np.asarray(transport["source_position_dataset"][:])
        destination_position = np.asarray(transport["destination_position_dataset"][:])
        displacement = np.asarray(transport["displacement_dataset"][:])
        for name, array in (
            ("source_position", source_position),
            ("destination_position", destination_position),
            ("displacement", displacement),
        ):
            if array.shape != (len(ids), 3):
                raise M4Error(f"{name} has shape {array.shape}, expected {(len(ids), 3)}")
        _finite_where_valid(source_position[None, ...], source_valid[None, ...], "source_position")
        _finite_where_valid(destination_position[None, ...], destination_valid[None, ...], "destination_position")
        pair_valid = source_valid & destination_valid
        if np.any(pair_valid):
            if not np.isfinite(displacement[pair_valid]).all():
                raise M4Error("displacement contains a non-finite valid endpoint pair")
            if not np.allclose(
                displacement[pair_valid],
                destination_position[pair_valid] - source_position[pair_valid],
                rtol=0.0,
                atol=1.0e-7,
            ):
                raise M4Error("displacement is not the keyed source-to-destination difference")
        if np.any(~pair_valid):
            missing_displacement = displacement[~pair_valid]
            if not np.isnan(missing_displacement).all():
                raise M4Error("missing endpoint pairs must have NaN displacement, never a fabricated transport")

        return {
            "case_id": interface["case_id"],
            "frames": len(time),
            "particles": len(ids),
            "initial_identity_complete": True,
            "all_frames_fixed_axis": True,
            "invalid_value_count": int((~valid).sum()),
            "native_exclusion_count": int(exclusion.sum()),
            "valid_source_count": int(source_valid.sum()),
            "valid_destination_count": int(destination_valid.sum()),
            "missing_destination_count": int((~destination_valid).sum()),
            "fate_inference": False,
        }


def validate_interface(path: Path, *, allow_pending: bool = False, verify_payload: bool = True) -> dict[str, Any]:
    """Validate a data_product interface and, when present, its normalized HDF5."""

    payload = load_interface(path, allow_pending=allow_pending)
    root = path.parent.resolve()
    hdf5_path = _relative_local(root, payload["normalized_hdf5"]["path"], "normalized_hdf5.path", must_exist=verify_payload)
    if verify_payload:
        actual = _file_binding(hdf5_path)
        if actual["bytes"] != payload["normalized_hdf5"]["bytes"] or actual["sha256"] != payload["normalized_hdf5"]["sha256"]:
            raise M4Error("normalized HDF5 does not match its interface binding")
        summary = _validate_hdf5(payload, hdf5_path)
    else:
        summary = {
            "case_id": payload["case_id"],
            "pending": payload["status"] == "template_pending_native_audit",
        }
    return {"interface": payload, "hdf5": hdf5_path, "summary": summary}


def _redact_attr(value: Any) -> Any:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, np.ndarray):
        if value.dtype.kind in "SU":
            return np.asarray([_redact_attr(item) for item in value])
        return value
    if isinstance(value, str) and (
        value.startswith("/")
        or "/home/" in value
        or "/worktrees/" in value
        or "CURRENT" in value
    ):
        return "portable/redacted-source-path"
    return value


def _copy_h5_node(source: h5py.Group, target: h5py.Group, name: str) -> None:
    item = source[name]
    if isinstance(item, h5py.Dataset):
        source.copy(name, target)
        copied = target[name]
        for key, value in item.attrs.items():
            copied.attrs[key] = _redact_attr(value)
        return
    group = target.create_group(name)
    for key, value in item.attrs.items():
        group.attrs[key] = _redact_attr(value)
    for child in item.keys():
        _copy_h5_node(item, group, child)


def _copy_sanitized_hdf5(source: Path, destination: Path, case_id: str) -> None:
    with h5py.File(source, "r") as source_handle, h5py.File(destination, "x") as target:
        for key, value in source_handle.attrs.items():
            target.attrs[key] = _redact_attr(value)
        target.attrs["m4_portable_case_id"] = case_id
        target.attrs["m4_portable_schema"] = BUNDLE_SCHEMA
        for name in source_handle.keys():
            _copy_h5_node(source_handle, target, name)


def _portable_metadata(value: Any, *, key: str = "") -> Any:
    """Remove host paths while retaining source receipt hashes and roles."""

    if isinstance(value, dict):
        return {str(name): _portable_metadata(item, key=str(name)) for name, item in value.items()}
    if isinstance(value, list):
        return [_portable_metadata(item, key=key) for item in value]
    if isinstance(value, str):
        if key.endswith("_dataset"):
            return value
        if value.startswith("/"):
            return f"portable/source-receipt/{Path(value).name or 'root'}"
        return value
    return value


def _portable_interface(source: Mapping[str, Any], hdf5: Path) -> dict[str, Any]:
    payload = json.loads(json.dumps(source))
    payload = _portable_metadata(payload)
    binding = _file_binding(hdf5, relative_path="normalized.h5")
    payload["normalized_hdf5"] = binding
    payload["portable_source_paths_redacted"] = True
    payload["source_receipts"] = [
        {
            **{key: value for key, value in receipt.items() if key != "path"},
            "path": f"portable/source-receipt/{Path(str(receipt.get('path', 'receipt'))).name}",
        }
        for receipt in source["source_receipts"]
    ]
    for key in ("conversion_report", "native_frame_scan", "native_lifecycle_sidecar"):
        item = payload.get(key)
        if isinstance(item, dict) and isinstance(item.get("path"), str):
            item["path"] = f"portable/source-receipt/{Path(item['path']).name}"
    return payload


def _artifact_map(root: Path) -> dict[str, dict[str, Any]]:
    return {
        key: _file_binding(root / filename, relative_path=filename)
        for key, filename in (
            ("normalized_hdf5", "normalized.h5"),
            ("interface", "interface.json"),
            ("evaluator", "evaluator.json"),
            ("reader_manifest", "reader-manifest.json"),
            ("runtime_adapter", "runtime/m4_portable_adapter.py"),
            ("runtime_l2_reader", "runtime/l2_reader.py"),
        )
    }


def _locate_l2_reader() -> Path:
    """Locate the existing read-only L2 reader for bundling.

    This is the same reader source used by the M2 bundle.  It is copied into
    the M4 runtime; the M2 portable builder itself is never imported or
    modified.
    """

    for parent in Path(__file__).resolve().parents:
        candidate = parent / "scripts" / "l2_reader.py"
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
    raise M4Error("cannot locate the existing L2 reader for the portable runtime")


def build_bundle(interface_path: Path, output_root: Path, *, allow_pending: bool = False) -> dict[str, Any]:
    """Build a relocatable M4 bundle around a data_product normalized input."""

    checked = validate_interface(interface_path, allow_pending=allow_pending, verify_payload=True)
    if checked["interface"]["status"] != "normalized_verified":
        raise M4Error("a pending native audit cannot be materialized as a portable M4 product")
    if output_root.exists() or output_root.is_symlink():
        raise M4Error(f"refusing to overwrite bundle root: {output_root}")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_root.with_name(output_root.name + f".partial-{os.getpid()}")
    if temporary.exists() or temporary.is_symlink():
        raise M4Error(f"stale partial bundle exists: {temporary}")
    temporary.mkdir()
    try:
        (temporary / "runtime").mkdir()
        _copy_sanitized_hdf5(checked["hdf5"], temporary / "normalized.h5", checked["interface"]["case_id"])
        portable_interface = _portable_interface(checked["interface"], temporary / "normalized.h5")
        _write_json(temporary / "interface.json", portable_interface)
        packaged = validate_interface(temporary / "interface.json", verify_payload=True)
        evaluator = {
            "schema": EVALUATOR_SCHEMA,
            "case_id": packaged["interface"]["case_id"],
            "checks": {
                "validity_aware_nonfinite_policy": True,
                "full_initial_identity_all_frames": packaged["summary"]["initial_identity_complete"],
                "endpoint_labels_semantic": True,
                "missing_endpoint_fate_not_inferred": packaged["summary"]["fate_inference"] is False,
            },
            "summary": packaged["summary"],
            "passed": True,
            "semantics": "diagnostic endpoint transport only; missing numerical nodes remain unknown or censored",
        }
        _write_json(temporary / "evaluator.json", evaluator)
        shutil.copyfile(Path(__file__), temporary / "runtime/m4_portable_adapter.py")
        shutil.copyfile(_locate_l2_reader(), temporary / "runtime/l2_reader.py")
        normalized_binding = _file_binding(temporary / "normalized.h5", relative_path="normalized.h5")
        _write_json(
            temporary / "reader-manifest.json",
            {
                "schema": "l2.f3.canonical_manifest.v1",
                "repository_root": ".",
                "cases": [
                    {
                        "case_id": packaged["interface"]["case_id"],
                        "hdf5": "normalized.h5",
                        "bytes": normalized_binding["bytes"],
                        "sha256": normalized_binding["sha256"],
                    }
                ],
            },
        )
        artifacts = _artifact_map(temporary)
        manifest = {
            "schema": BUNDLE_SCHEMA,
            "case_id": packaged["interface"]["case_id"],
            "interface": "interface.json",
            "artifacts": artifacts,
            "runtime": {"adapter": "runtime/m4_portable_adapter.py", "source_paths_redacted": True},
            "portable_policy": {
                "native_decoder_in_bundle": False,
                "raw_native_payload_in_bundle": False,
                "physical_fate_inferred": False,
                "m2_bundle_modified": False,
            },
        }
        _write_json(temporary / "manifest.json", manifest)
        os.replace(temporary, output_root)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return validate_bundle(output_root)


def _assert_bundle_path(root: Path, binding: Mapping[str, Any], label: str) -> Path:
    value = binding.get("path")
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise M4Error(f"{label} is not a relative bundle artifact")
    candidate = (root / value).resolve()
    if not candidate.is_relative_to(root.resolve()) or candidate.is_symlink() or not candidate.is_file():
        raise M4Error(f"{label} escapes the bundle or is not regular")
    actual = _file_binding(candidate, relative_path=value)
    if actual["bytes"] != binding.get("bytes") or actual["sha256"] != binding.get("sha256"):
        raise M4Error(f"{label} hash does not match the bundle file")
    return candidate


def _walk_portable_metadata(value: Any, location: str = "manifest", *, key: str = "") -> None:
    if isinstance(value, dict):
        for name, item in value.items():
            _walk_portable_metadata(item, f"{location}.{name}", key=str(name))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _walk_portable_metadata(item, f"{location}[{index}]", key=key)
    elif isinstance(value, str) and value.startswith("/") and not key.endswith("_dataset"):
        raise M4Error(f"absolute host path remains in portable metadata at {location}")


def validate_bundle(bundle_root: Path, *, denied_probe_paths: Iterable[Path] = ()) -> dict[str, Any]:
    """Validate a relocated bundle using only files under ``bundle_root``."""

    root = bundle_root.resolve()
    if bundle_root.is_symlink() or not root.is_dir():
        raise M4Error(f"bundle root is not a regular directory: {bundle_root}")
    for denied in denied_probe_paths:
        if Path(denied).exists() or Path(denied).is_symlink():
            raise M4Error(f"denied source path remains visible: {denied}")
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise M4Error("bundle manifest is missing")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise M4Error("bundle manifest is not valid JSON") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != BUNDLE_SCHEMA:
        raise M4Error("unsupported M4 portable bundle schema")
    _walk_portable_metadata({key: value for key, value in manifest.items() if key != "artifacts"})
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise M4Error("bundle manifest lacks artifacts")
    required = {
        "normalized_hdf5",
        "interface",
        "evaluator",
        "reader_manifest",
        "runtime_adapter",
        "runtime_l2_reader",
    }
    if not required.issubset(artifacts):
        raise M4Error(f"bundle manifest lacks artifacts: {sorted(required.difference(artifacts))}")
    files = {name: _assert_bundle_path(root, binding, name) for name, binding in artifacts.items()}
    interface_payload = json.loads(files["interface"].read_text(encoding="utf-8"))
    if not isinstance(interface_payload, dict):
        raise M4Error("bundled interface is not an object")
    _walk_portable_metadata(interface_payload, "interface")
    if interface_payload.get("normalized_hdf5", {}).get("path") != "normalized.h5":
        raise M4Error("bundled interface does not bind the bundled normalized HDF5")
    checked = validate_interface(files["interface"], verify_payload=True)
    if checked["hdf5"] != files["normalized_hdf5"].resolve():
        raise M4Error("interface and artifact normalized HDF5 paths disagree")
    evaluator = json.loads(files["evaluator"].read_text(encoding="utf-8"))
    if evaluator.get("schema") != EVALUATOR_SCHEMA or evaluator.get("passed") is not True:
        raise M4Error("bundled no-model evaluator did not pass")
    if evaluator.get("summary") != checked["summary"]:
        raise M4Error("bundled evaluator summary disagrees with recomputation")
    reader_manifest = json.loads(files["reader_manifest"].read_text(encoding="utf-8"))
    _walk_portable_metadata(reader_manifest, "reader_manifest")
    if reader_manifest.get("schema") != "l2.f3.canonical_manifest.v1" or reader_manifest.get("repository_root") != ".":
        raise M4Error("bundled L2 reader manifest is not portable")
    cases = reader_manifest.get("cases")
    if not isinstance(cases, list) or len(cases) != 1 or not isinstance(cases[0], dict):
        raise M4Error("bundled L2 reader manifest must contain one case")
    reader_case = cases[0]
    normalized_binding = artifacts["normalized_hdf5"]
    if (
        reader_case.get("case_id") != manifest["case_id"]
        or reader_case.get("hdf5") != "normalized.h5"
        or reader_case.get("bytes") != normalized_binding.get("bytes")
        or reader_case.get("sha256") != normalized_binding.get("sha256")
    ):
        raise M4Error("bundled L2 reader manifest disagrees with normalized HDF5")
    if manifest.get("portable_policy", {}).get("physical_fate_inferred") is not False:
        raise M4Error("bundle does not forbid physical-fate inference")
    return {
        "schema": VALIDATION_SCHEMA,
        "case_id": manifest["case_id"],
        "portable": True,
        "summary": checked["summary"],
        "labels": {
            "valid_source": checked["summary"]["valid_source_count"],
            "valid_destination": checked["summary"]["valid_destination_count"],
            "missing_destination": checked["summary"]["missing_destination_count"],
        },
        "source_paths_redacted": True,
        "physical_fate_inferred": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="package a data_product normalized input")
    build.add_argument("--interface", required=True, type=Path)
    build.add_argument("--output", required=True, type=Path)
    build.add_argument("--allow-pending", action="store_true")
    validate = sub.add_parser("validate", help="validate a relocated M4 bundle")
    validate.add_argument("--bundle-root", required=True, type=Path)
    validate.add_argument("--probe-denied-path", action="append", default=[], type=Path)
    interface = sub.add_parser("validate-interface", help="validate a data_product interface")
    interface.add_argument("--interface", required=True, type=Path)
    interface.add_argument("--allow-pending", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "build":
            result = build_bundle(args.interface, args.output, allow_pending=args.allow_pending)
        elif args.command == "validate-interface":
            result = validate_interface(args.interface, allow_pending=args.allow_pending)
        else:
            result = validate_bundle(args.bundle_root, denied_probe_paths=args.probe_denied_path)
    except (OSError, M4Error, ValueError, KeyError) as exc:
        print(f"m4-portable-adapter: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
