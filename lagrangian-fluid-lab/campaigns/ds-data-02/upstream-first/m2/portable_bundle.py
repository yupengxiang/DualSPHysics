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
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import h5py
import numpy as np


# A built package carries both this module and the small existing manifest
# reader beside one another.  Prefer that sibling before falling back to the
# development worktree; replay therefore has no dependency on the worktree.
_LOCAL_ROOT = Path(__file__).resolve().parent
_WORKTREE_LAB_ROOT = next(
    (parent for parent in Path(__file__).resolve().parents if (parent / "scripts" / "l2_reader.py").is_file()),
    None,
)
try:
    from . import l2_reader
except ImportError:
    _bundled_reader = _LOCAL_ROOT / "l2_reader.py"
    if _bundled_reader.is_file():
        if str(_LOCAL_ROOT) not in sys.path:
            sys.path.insert(0, str(_LOCAL_ROOT))
        import l2_reader  # type: ignore[no-redef]
    else:  # pragma: no cover - only used by an unbuilt development checkout
        if _WORKTREE_LAB_ROOT is None:
            raise RuntimeError("portable_bundle.py cannot locate the existing L2 reader")
        if str(_WORKTREE_LAB_ROOT) not in sys.path:
            sys.path.insert(0, str(_WORKTREE_LAB_ROOT))
        try:
            from scripts import l2_reader  # type: ignore[no-redef]
        except ImportError as exc:
            raise RuntimeError(
                "portable_bundle.py requires the bundled l2_reader.py or "
                "lagrangian-fluid-lab/scripts/l2_reader.py"
            ) from exc


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


def _file_binding(path: Path, *, relative_path: str | None = None) -> dict[str, Any]:
    return {
        "path": relative_path or path.name,
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _xml_node_evidence(node: ET.Element) -> dict[str, Any]:
    """Keep generated XML geometry/control evidence without path-bearing text."""

    tag = node.tag.rsplit("}", 1)[-1]
    return {
        "tag": tag,
        "attributes": {str(key): str(value) for key, value in sorted(node.attrib.items())},
        "children": [_xml_node_evidence(child) for child in list(node)],
    }


def _read_source_evidence(
    source_report: Path,
    *,
    source_hdf5: Path,
    owner_metadata_override: Path | None = None,
    generated_xml_override: Path | None = None,
) -> dict[str, Any]:
    """Read source evidence and bind the exact HDF5 bytes to the report."""

    report = json.loads(source_report.read_text(encoding="utf-8"))
    expected_source_hash = report.get("output_sha256")
    if not isinstance(expected_source_hash, str) or not _SHA256.fullmatch(expected_source_hash):
        raise PortableBundleError("conversion report lacks a valid output_sha256")
    if not source_hdf5.is_file() or source_hdf5.is_symlink():
        raise PortableBundleError(f"source HDF5 is not a regular file: {source_hdf5}")
    source_bytes = source_hdf5.stat().st_size
    source_hash = _sha256(source_hdf5)
    if source_hash != expected_source_hash:
        raise PortableBundleError(
            "source HDF5 hash disagrees with conversion report output_sha256"
        )
    provenance = report.get("source_provenance", {})
    owner_info = provenance.get("owner_metadata", {})
    xml_info = provenance.get("generated_xml", {})
    owner_metadata: dict[str, Any] = {}
    generated_xml: dict[str, Any] = {}
    receipts: dict[str, Any] = {
        "schema": "ds-data-02.m2.source-receipts.v1",
        "conversion_report_sha256": _sha256(source_report),
        "source_hdf5": {
            "bytes": source_bytes,
            "sha256": source_hash,
            "report_output_sha256": expected_source_hash,
            "matches_conversion_report": True,
        },
        "paths_published": False,
    }
    owner_path = (
        owner_metadata_override
        if owner_metadata_override is not None
        else (Path(owner_info["path"]) if isinstance(owner_info, dict) and owner_info.get("path") else None)
    )
    if owner_metadata_override is not None and (
        not owner_metadata_override.is_file() or owner_metadata_override.is_symlink()
    ):
        raise PortableBundleError(f"bound owner metadata is not a regular file: {owner_metadata_override}")
    if owner_path is not None and owner_path.is_file() and not owner_path.is_symlink():
        actual_hash = _sha256(owner_path)
        expected_hash = owner_info.get("sha256")
        if isinstance(expected_hash, str) and actual_hash != expected_hash:
            raise PortableBundleError("owner metadata hash disagrees with conversion report")
        owner_metadata = json.loads(owner_path.read_text(encoding="utf-8"))
        if not isinstance(owner_metadata, dict):
            raise PortableBundleError("owner metadata must be a JSON object")
        receipts["owner_metadata"] = {"available": True, "bytes": owner_path.stat().st_size, "sha256": actual_hash}
    else:
        receipts["owner_metadata"] = {"available": False, "reason": "source report has no readable owner metadata"}

    xml_path = (
        generated_xml_override
        if generated_xml_override is not None
        else (Path(xml_info["path"]) if isinstance(xml_info, dict) and xml_info.get("path") else None)
    )
    if generated_xml_override is not None and (
        not generated_xml_override.is_file() or generated_xml_override.is_symlink()
    ):
        raise PortableBundleError(f"bound generated XML is not a regular file: {generated_xml_override}")
    if xml_path is not None and xml_path.is_file() and not xml_path.is_symlink():
        actual_hash = _sha256(xml_path)
        expected_hash = xml_info.get("sha256")
        if isinstance(expected_hash, str) and actual_hash != expected_hash:
            raise PortableBundleError("generated XML hash disagrees with conversion report")
        try:
            root = ET.fromstring(xml_path.read_bytes())
        except ET.ParseError as exc:
            raise PortableBundleError("generated XML is not parseable") from exc
        generated_xml = _xml_node_evidence(root)
        receipts["generated_xml"] = {"available": True, "bytes": xml_path.stat().st_size, "sha256": actual_hash}
    else:
        receipts["generated_xml"] = {"available": False, "reason": "source report has no readable generated XML"}
    return {"report": report, "owner_metadata": owner_metadata, "generated_xml": generated_xml, "receipts": receipts}


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


def _make_labels(hdf5_path: Path, labels_path: Path) -> dict[str, Any]:
    """Write endpoint labels keyed by the native ``(Zone,Idp)`` axis.

    The source and destination arrays are copied from the existing trajectory
    fields at frame zero and the final native frame.  No nearest-neighbour
    matching or re-numbering is introduced.  The resulting HDF5 sidecar keeps
    the numerical transport labels separate from the full state while making
    their identity binding explicit.
    """

    with h5py.File(hdf5_path, "r") as handle:
        required = {
            "particle_id",
            "particle_zone",
            "initial_type",
            "initial_mk",
            "position",
            "type",
            "mk",
            "valid",
            "time",
        }
        missing = sorted(required.difference(handle.keys()))
        if missing:
            raise PortableBundleError(f"cannot make labels; HDF5 fields missing: {missing}")
        ids = np.asarray(handle["particle_id"][:])
        zones = np.asarray(handle["particle_zone"][:])
        source_type = np.asarray(handle["initial_type"][:])
        source_mk = np.asarray(handle["initial_mk"][:])
        source_position = np.asarray(handle["position"][0])
        destination_position = np.asarray(handle["position"][-1])
        destination_type = np.asarray(handle["type"][-1])
        destination_mk = np.asarray(handle["mk"][-1])
        valid_source = np.asarray(handle["valid"][0], dtype=bool)
        valid_destination = np.asarray(handle["valid"][-1], dtype=bool)
        observed_all_frames = np.asarray(handle["valid"][:], dtype=bool).all(axis=0)
        time = np.asarray(handle["time"][:], dtype=np.float64)
    n = len(ids)
    if not (
        len(zones)
        == len(source_type)
        == len(source_mk)
        == len(destination_type)
        == len(destination_mk)
        == source_position.shape[0]
        == destination_position.shape[0]
        == n
    ):
        raise PortableBundleError("identity and label arrays have inconsistent lengths")
    if len(time) == 0 or valid_source.shape != (n,) or valid_destination.shape != (n,):
        raise PortableBundleError("trajectory time or validity fields have invalid shapes")
    displacement = destination_position - source_position
    with h5py.File(labels_path, "x") as labels:
        labels.attrs["schema"] = "ds-data-02.m2.portable-labels.v2"
        labels.attrs["key"] = "(Zone,Idp)"
        labels.attrs["source_frame"] = 0
        labels.attrs["destination_frame"] = len(time) - 1
        labels.attrs["source_time_s"] = float(time[0])
        labels.attrs["destination_time_s"] = float(time[-1])
        labels.attrs["observation_window_frames_json"] = json.dumps([0, len(time) - 1])
        labels.attrs["destination_region_spacing_m"] = 0.05
        labels.attrs["label_semantics"] = (
            "source/destination endpoints and displacement are copied by native typed identity; "
            "destination_region is a deterministic 5 cm bin of native final position"
        )
        labels.create_dataset("particle_id", data=ids, chunks=True)
        labels.create_dataset("particle_zone", data=zones, chunks=True)
        labels.create_dataset("source_position_m", data=source_position, chunks=True)
        labels.create_dataset("destination_position_m", data=destination_position, chunks=True)
        labels.create_dataset("displacement_m", data=displacement, chunks=True)
        labels.create_dataset("source_type", data=source_type, chunks=True)
        labels.create_dataset("source_mk", data=source_mk, chunks=True)
        labels.create_dataset("destination_type", data=destination_type, chunks=True)
        labels.create_dataset("destination_mk", data=destination_mk, chunks=True)
        labels.create_dataset("valid_source", data=valid_source, chunks=True)
        labels.create_dataset("valid_destination", data=valid_destination, chunks=True)
        labels.create_dataset("observed_all_frames", data=observed_all_frames, chunks=True)
        labels.create_dataset(
            "destination_region",
            data=np.asarray(_destination_regions(destination_position), dtype=np.int64),
            chunks=True,
        )
    return {
        "schema": "ds-data-02.m2.portable-labels.v2",
        "key": ["particle_zone", "particle_id"],
        "particle_count": n,
        "source_frame": 0,
        "destination_frame": len(time) - 1,
        "source_time_s": float(time[0]),
        "destination_time_s": float(time[-1]),
        "observed_all_frames_count": int(observed_all_frames.sum()),
        "invalid_source_count": int((~valid_source).sum()),
        "invalid_destination_count": int((~valid_destination).sum()),
        "destination_region_spacing_m": 0.05,
        "semantics": "native identity keyed source/destination positions, displacement, type/mk, validity, and destination regions",
    }


def _build_sidecars(
    output_root: Path,
    *,
    case_id: str,
    source_report: Path,
    source_hdf5: Path,
    hdf5_path: Path,
    labels_path: Path,
    owner_metadata: Path | None = None,
    generated_xml: Path | None = None,
    source_evidence: dict[str, Any] | None = None,
) -> None:
    if source_evidence is None:
        try:
            source_evidence = _read_source_evidence(
                source_report,
                source_hdf5=source_hdf5,
                owner_metadata_override=owner_metadata,
                generated_xml_override=generated_xml,
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise PortableBundleError(f"cannot read source conversion report: {source_report}") from exc
    report = source_evidence["report"]
    owner = source_evidence["owner_metadata"]
    report_physical = report.get("hash_scopes", {}).get("physical_condition", {})
    if not isinstance(report_physical, dict):
        report_physical = {}
    physical = {
        "geometry": report_physical.get("geometry") or owner.get("geometry"),
        "geometry_family_id": report_physical.get("geometry_family_id") or owner.get("geometry_family_id"),
        "control_family_id": report_physical.get("control_family_id") or owner.get("control_family_id"),
        "recipe_id": report_physical.get("recipe_id") or owner.get("recipe_id"),
        "event_window": report_physical.get("event_window") or owner.get("event_window", {}),
        "family_id": report_physical.get("family_id") or owner.get("family_id"),
        "physical_case_id": report_physical.get("physical_case_id") or owner.get("physical_case_id"),
        "lineage_group_id": report_physical.get("lineage_group_id") or owner.get("lineage_group_id"),
        "mechanism_id": report_physical.get("mechanism_id") or owner.get("mechanism_id"),
        "paired_background_id": report_physical.get("paired_background_id") or owner.get("paired_background_id"),
        "view_id": report_physical.get("view_id") or owner.get("view_id"),
    }
    if not isinstance(physical.get("geometry"), dict):
        raise PortableBundleError(
            "source report and owner metadata lack physical geometry; refusing synthetic geometry"
        )
    geometry = {
        "schema": "ds-data-02.m2.geometry.v1",
        "case_id": case_id,
        "coordinate_frame": report.get("coordinate_frame"),
        "solver_dimension": report.get("solver_dimension", {}).get("solver_dimension"),
        "geometry_family_id": physical.get("geometry_family_id"),
        "geometry_sha256": report.get("source_provenance", {}).get("geometry_sha256"),
        "geometry": physical["geometry"],
        "parameter_values": owner.get("parameter_values", {}),
        "generated_xml": source_evidence["generated_xml"],
        "owner_metadata_sha256": source_evidence["receipts"].get("owner_metadata", {}).get("sha256"),
        "generated_xml_sha256": source_evidence["receipts"].get("generated_xml", {}).get("sha256"),
        "units": report.get("units", {}),
    }
    control = {
        "schema": "ds-data-02.m2.control.v1",
        "case_id": case_id,
        "control_family_id": physical.get("control_family_id"),
        "recipe_id": physical.get("recipe_id"),
        "event_window": physical.get("event_window", {}),
        "solver_parameters": owner.get("solver_parameters", report.get("hash_scopes", {}).get("numerical_parameters", {}).get("solver_parameters", {})),
        "observables": owner.get("observables", {}),
        "error_budget": owner.get("error_budget", {}),
        "numerical_parameters_sha256": report.get("hash_scopes", {}).get("numerical_parameters_sha256"),
        "control_sha256": report.get("source_provenance", {}).get("control_sha256"),
        "owner_metadata_sha256": source_evidence["receipts"].get("owner_metadata", {}).get("sha256"),
        "generated_xml_sha256": source_evidence["receipts"].get("generated_xml", {}).get("sha256"),
        "initial_exclusion_ledger": report.get("typed_identity", {}).get("initial_exclusion_ledger", {}),
        "conversion_evidence": report.get("conversion_claim"),
    }
    _make_labels(hdf5_path, labels_path)
    _write_json(output_root / "geometry.json", geometry)
    _write_json(output_root / "control.json", control)
    _write_json(output_root / "source-receipts.json", source_evidence["receipts"])


def _evaluator_score(hdf5_path: Path, labels_path: Path) -> dict[str, Any]:
    """Recompute endpoint labels and meaningful keyed transport diagnostics."""

    with h5py.File(hdf5_path, "r") as trajectory, h5py.File(labels_path, "r") as labels:
        source_position = np.asarray(trajectory["position"][0])
        destination_position = np.asarray(trajectory["position"][-1])
        recomputed_displacement = destination_position - source_position
        label_source = np.asarray(labels["source_position_m"][:])
        label_destination = np.asarray(labels["destination_position_m"][:])
        label_displacement = np.asarray(labels["displacement_m"][:])
        label_region = np.asarray(labels["destination_region"][:])
        source_type = np.asarray(labels["source_type"][:])
        observed_all_frames = np.asarray(labels["observed_all_frames"][:], dtype=bool)
        if label_source.shape != source_position.shape or label_destination.shape != destination_position.shape:
            raise PortableBundleError("transport labels do not match trajectory endpoint shape")
        label_recompute_error = float(
            max(
                np.max(np.abs(label_source - source_position)),
                np.max(np.abs(label_destination - destination_position)),
                np.max(np.abs(label_displacement - recomputed_displacement)),
            )
        )
        recomputed_regions = np.asarray(_destination_regions(destination_position), dtype=np.int64)
        region_mismatch_count = int(np.count_nonzero(recomputed_regions != label_region))
        displacement_norm = np.linalg.norm(recomputed_displacement, axis=1)
        fluid = source_type == 3
        moving = displacement_norm > 1e-6
        permutation_error = float(np.sqrt(np.mean((label_destination[::-1] - label_destination) ** 2)))
        perturbed_destination = label_destination.copy()
        perturbed_destination[0, 0] += 1e-4
        field_perturbed_displacement = perturbed_destination - label_source
        field_perturbation = float(
            np.max(np.abs(field_perturbed_displacement - label_displacement))
        )
        transport_summary = {
            "particle_count": int(len(displacement_norm)),
            "observed_all_frames_count": int(observed_all_frames.sum()),
            "moving_particle_count": int(moving.sum()),
            "moving_fluid_count": int((moving & fluid).sum()),
            "mean_displacement_m": float(displacement_norm.mean()),
            "max_displacement_m": float(displacement_norm.max()),
            "destination_region_count": int(len(np.unique(recomputed_regions))),
        }
    checks = {
        "label_recomputation_passed": label_recompute_error <= 1e-6,
        "region_recomputation_passed": region_mismatch_count == 0,
        "identity_permutation_rejected": permutation_error > 1e-9,
        "field_perturbation_rejected": field_perturbation > 0.0,
    }
    return {
        "schema": "ds-data-02.m2.no-model-evaluator.v2",
        "label_recompute_max_abs_m": label_recompute_error,
        "region_mismatch_count": region_mismatch_count,
        "identity_permutation_rmse_m": permutation_error,
        "field_perturbation_delta_m": field_perturbation,
        "transport_summary": transport_summary,
        "checks": checks,
        "passed": all(checks.values()),
        "semantics": "endpoint labels are recomputed from the native typed identity axis; negatives permute destination identity or perturb a published field",
    }


def _bundle_runtime(output_root: Path) -> None:
    """Copy the reader and evaluator implementation into the package."""

    runtime = output_root / "runtime"
    runtime.mkdir()
    if _WORKTREE_LAB_ROOT is None:
        raise PortableBundleError("cannot locate the existing worktree L2 reader")
    reader_source = _WORKTREE_LAB_ROOT / "scripts" / "l2_reader.py"
    if not reader_source.is_file() or reader_source.is_symlink():
        raise PortableBundleError(f"existing L2 reader source is missing: {reader_source}")
    shutil.copyfile(Path(__file__), runtime / "portable_bundle.py")
    shutil.copyfile(reader_source, runtime / "l2_reader.py")


def build_bundle(
    source_hdf5: Path,
    source_report: Path,
    output_root: Path,
    case_id: str,
    *,
    owner_metadata: Path | None = None,
    generated_xml: Path | None = None,
) -> dict[str, Any]:
    """Materialise a sanitized bundle around an existing direct-conversion HDF5."""

    if output_root.exists() or output_root.is_symlink():
        raise PortableBundleError(f"refusing to overwrite bundle root: {output_root}")
    if not source_hdf5.is_file() or source_hdf5.is_symlink():
        raise PortableBundleError(f"source HDF5 is not a regular file: {source_hdf5}")
    try:
        source_evidence = _read_source_evidence(
            source_report,
            source_hdf5=source_hdf5,
            owner_metadata_override=owner_metadata,
            generated_xml_override=generated_xml,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise PortableBundleError(f"cannot read source conversion report: {source_report}") from exc
    output_root.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_root.with_name(output_root.name + f".partial-{os.getpid()}")
    if temporary.exists() or temporary.is_symlink():
        raise PortableBundleError(f"stale partial bundle exists: {temporary}")
    temporary.mkdir()
    try:
        _bundle_runtime(temporary)
        _copy_sanitized_hdf5(source_hdf5, temporary / "trajectory.h5", case_id)
        _build_sidecars(
            temporary,
            case_id=case_id,
            source_report=source_report,
            source_hdf5=source_hdf5,
            hdf5_path=temporary / "trajectory.h5",
            labels_path=temporary / "labels.h5",
            owner_metadata=owner_metadata,
            generated_xml=generated_xml,
            source_evidence=source_evidence,
        )
        _write_json(
            temporary / "evaluator.json",
            _evaluator_score(temporary / "trajectory.h5", temporary / "labels.h5"),
        )
        trajectory_binding = _file_binding(temporary / "trajectory.h5")
        reader_manifest = {
            "schema": READER_SCHEMA,
            "repository_root": ".",
            "cases": [{"case_id": case_id, "hdf5": "trajectory.h5", **trajectory_binding}],
        }
        _write_json(temporary / "reader-manifest.json", reader_manifest)
        source_receipts = json.loads((temporary / "source-receipts.json").read_text(encoding="utf-8"))
        artifacts = {
            name: _file_binding(temporary / filename)
            for name, filename in (
                ("trajectory", "trajectory.h5"),
                ("geometry", "geometry.json"),
                ("control", "control.json"),
                ("labels", "labels.h5"),
                ("evaluator", "evaluator.json"),
                ("source_receipts", "source-receipts.json"),
                ("reader_manifest", "reader-manifest.json"),
            )
        }
        artifacts["runtime_portable_bundle"] = _file_binding(
            temporary / "runtime/portable_bundle.py",
            relative_path="runtime/portable_bundle.py",
        )
        artifacts["runtime_l2_reader"] = _file_binding(
            temporary / "runtime/l2_reader.py",
            relative_path="runtime/l2_reader.py",
        )
        manifest = {
            "schema": SCHEMA,
            "case_id": case_id,
            "reader_manifest": "reader-manifest.json",
            "artifacts": artifacts,
            "denied_path_markers": list(_DEFAULT_DENIED_MARKERS),
            "field_semantics": {
                "available": list(_H5_FIELDS),
                "label_fields": [
                    "particle_id",
                    "particle_zone",
                    "source_position_m",
                    "destination_position_m",
                    "displacement_m",
                    "source_type",
                    "source_mk",
                    "destination_type",
                    "destination_mk",
                    "valid_source",
                    "valid_destination",
                    "observed_all_frames",
                    "destination_region",
                ],
                "unavailable": ["source_solver_paths", "raw_bi4_path", "decoder_path"],
                "validity_contract": "closed fixed identity axis; expected complete for F1 reference",
            },
            "source_evidence": {
                "source_report_sha256": _json_hash(source_report),
                "source_report_schema": "ds-data-02.bi4-direct-conversion.v1",
                "source_hdf5": source_receipts["source_hdf5"],
                "owner_metadata_and_generated_xml_read_at_build": True,
                "paths_published": False,
            },
        }
        _write_json(temporary / "manifest.json", manifest)
        os.replace(temporary, output_root)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return validate_bundle(output_root)


def _walk_json_strings(value: Any, location: str, denied: tuple[str, ...]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            _walk_json_strings(item, f"{location}.{key}", denied)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _walk_json_strings(item, f"{location}[{index}]", denied)
    elif isinstance(value, str):
        if any(marker in value for marker in denied):
            raise PortableBundleError(f"denied original path marker at {location}: {value!r}")
        if value.startswith("/") and not value.startswith("https://"):
            raise PortableBundleError(f"absolute path in portable metadata at {location}: {value!r}")


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


def _h5_scalar_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _validate_labels(
    labels_path: Path,
    trajectory_path: Path,
    *,
    denied: tuple[str, ...],
) -> dict[str, Any]:
    """Check every published transport label against native trajectory rows."""

    required = {
        "particle_id",
        "particle_zone",
        "source_position_m",
        "destination_position_m",
        "displacement_m",
        "source_type",
        "source_mk",
        "destination_type",
        "destination_mk",
        "valid_source",
        "valid_destination",
        "observed_all_frames",
        "destination_region",
    }
    with h5py.File(labels_path, "r") as labels, h5py.File(trajectory_path, "r") as trajectory:
        _check_hdf5_attrs(labels, denied)
        if _h5_scalar_text(labels.attrs.get("schema", "")) != "ds-data-02.m2.portable-labels.v2":
            raise PortableBundleError("transport label schema is unsupported")
        missing = sorted(required.difference(labels.keys()))
        if missing:
            raise PortableBundleError(f"transport labels are missing fields: {missing}")
        ids = np.asarray(trajectory["particle_id"][:])
        zones = np.asarray(trajectory["particle_zone"][:])
        n = len(ids)
        t = len(trajectory["time"])
        expected_shapes = {
            "particle_id": (n,),
            "particle_zone": (n,),
            "source_position_m": (n, 3),
            "destination_position_m": (n, 3),
            "displacement_m": (n, 3),
            "source_type": (n,),
            "source_mk": (n,),
            "destination_type": (n,),
            "destination_mk": (n,),
            "valid_source": (n,),
            "valid_destination": (n,),
            "observed_all_frames": (n,),
            "destination_region": (n,),
        }
        for name, shape in expected_shapes.items():
            if tuple(labels[name].shape) != shape:
                raise PortableBundleError(f"transport label {name} shape {labels[name].shape} != {shape}")
        if not np.array_equal(np.asarray(labels["particle_id"][:]), ids):
            raise PortableBundleError("transport labels changed particle IDs")
        if not np.array_equal(np.asarray(labels["particle_zone"][:]), zones):
            raise PortableBundleError("transport labels changed particle zones")
        source_position = np.asarray(trajectory["position"][0])
        destination_position = np.asarray(trajectory["position"][-1])
        if not np.array_equal(np.asarray(labels["source_position_m"][:]), source_position):
            raise PortableBundleError("source transport positions do not match frame zero")
        if not np.array_equal(np.asarray(labels["destination_position_m"][:]), destination_position):
            raise PortableBundleError("destination transport positions do not match final frame")
        displacement = np.asarray(labels["displacement_m"][:])
        if not np.allclose(displacement, destination_position - source_position, rtol=0.0, atol=1e-7):
            raise PortableBundleError("transport displacement is not source-to-destination")
        if not np.array_equal(np.asarray(labels["source_type"][:]), np.asarray(trajectory["initial_type"][:])):
            raise PortableBundleError("source type labels do not match native initial type")
        if not np.array_equal(np.asarray(labels["source_mk"][:]), np.asarray(trajectory["initial_mk"][:])):
            raise PortableBundleError("source mk labels do not match native initial mk")
        if not np.array_equal(np.asarray(labels["destination_type"][:]), np.asarray(trajectory["type"][-1])):
            raise PortableBundleError("destination type labels do not match native final type")
        if not np.array_equal(np.asarray(labels["destination_mk"][:]), np.asarray(trajectory["mk"][-1])):
            raise PortableBundleError("destination mk labels do not match native final mk")
        valid = np.asarray(trajectory["valid"][:], dtype=bool)
        for label_name, expected in (
            ("valid_source", valid[0]),
            ("valid_destination", valid[-1]),
            ("observed_all_frames", valid.all(axis=0)),
        ):
            if not np.array_equal(np.asarray(labels[label_name][:], dtype=bool), expected):
                raise PortableBundleError(f"transport label {label_name} disagrees with native validity")
        recomputed_regions = np.asarray(_destination_regions(destination_position), dtype=np.int64)
        if not np.array_equal(np.asarray(labels["destination_region"][:]), recomputed_regions):
            raise PortableBundleError("destination regions are not computed from final native positions")
        times = np.asarray(trajectory["time"][:])
        source_time = float(labels.attrs.get("source_time_s", np.nan))
        destination_time = float(labels.attrs.get("destination_time_s", np.nan))
        if not np.isclose(source_time, times[0]) or not np.isclose(destination_time, times[-1]):
            raise PortableBundleError("transport label observation times do not match native time")
        return {
            "schema": "ds-data-02.m2.portable-labels.v2",
            "particles": n,
            "frames": t,
            "observed_all_frames_count": int(np.asarray(labels["observed_all_frames"], dtype=bool).sum()),
            "invalid_source_count": int((~np.asarray(labels["valid_source"], dtype=bool)).sum()),
            "invalid_destination_count": int((~np.asarray(labels["valid_destination"], dtype=bool)).sum()),
        }


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
        try:
            dimension = int(handle.attrs.get("solver_dimension", -1))
        except (TypeError, ValueError):
            dimension = -1
        if dimension != 3:
            raise PortableBundleError(f"portable trajectory must be 3-D, got solver_dimension={dimension}")
        if _h5_scalar_text(handle.attrs.get("identity_key", "")) != "(Zone,Idp)":
            raise PortableBundleError("portable trajectory identity key is not (Zone,Idp)")
        if not _h5_scalar_text(handle.attrs.get("coordinate_frame", "")).strip():
            raise PortableBundleError("portable trajectory lacks coordinate-frame metadata")
        try:
            units = json.loads(_h5_scalar_text(handle.attrs.get("units_json", "{}")))
        except json.JSONDecodeError as exc:
            raise PortableBundleError("portable trajectory units_json is invalid") from exc
        if not isinstance(units, dict) or sorted(units) != ["density", "mass", "position", "pressure", "time", "velocity"]:
            raise PortableBundleError("portable trajectory units_json is incomplete")
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
        if valid.dtype.kind not in "biu":
            raise PortableBundleError("valid mask must be boolean or integer-valued")
        for name in ("initial_mass", "initial_type", "initial_mk"):
            if not np.isfinite(handle[name][:]).all():
                raise PortableBundleError(f"non-finite initial field: {name}")
        for start in range(0, t, 8):
            stop = min(t, start + 8)
            if not np.isfinite(handle["position"][start:stop]).all():
                raise PortableBundleError(f"non-finite position near frame {start}")
            if not np.isfinite(handle["velocity"][start:stop]).all():
                raise PortableBundleError(f"non-finite velocity near frame {start}")
            for name in ("density", "mass", "pressure", "type", "mk"):
                if not np.isfinite(handle[name][start:stop]).all():
                    raise PortableBundleError(f"non-finite {name} near frame {start}")
        return {"case_id": case_id, "frames": t, "particles": n, "complete_validity": bool(np.asarray(valid[:], dtype=bool).all())}


def validate_bundle(
    bundle_root: Path,
    *,
    denied_probe_paths: tuple[Path, ...] = (),
) -> dict[str, Any]:
    bundle_root = bundle_root.resolve()
    for denied_path in denied_probe_paths:
        if denied_path.exists() or denied_path.is_symlink():
            raise PortableBundleError(f"denied source path remains accessible: {denied_path}")
    manifest_path = bundle_root / "manifest.json"
    if not manifest_path.is_file():
        raise PortableBundleError(f"missing bundle manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != SCHEMA:
        raise PortableBundleError(f"unsupported bundle schema: {manifest.get('schema')!r}")
    denied = tuple(manifest.get("denied_path_markers", _DEFAULT_DENIED_MARKERS))
    if not denied:
        raise PortableBundleError("portable bundle must declare denied path markers")
    # The marker declarations are policy, not published source paths; all
    # other manifest values must pass the path scan.
    _walk_json_strings(
        {key: value for key, value in manifest.items() if key != "denied_path_markers"},
        "manifest",
        denied,
    )
    artifacts = manifest.get("artifacts")
    case_id = manifest.get("case_id")
    if not isinstance(case_id, str) or not isinstance(artifacts, dict):
        raise PortableBundleError("bundle manifest lacks case_id or artifacts")
    required_artifacts = {
        "trajectory",
        "geometry",
        "control",
        "labels",
        "evaluator",
        "source_receipts",
        "reader_manifest",
        "runtime_portable_bundle",
        "runtime_l2_reader",
    }
    missing_artifacts = sorted(required_artifacts.difference(artifacts))
    if missing_artifacts:
        raise PortableBundleError(f"bundle manifest lacks required artifacts: {missing_artifacts}")
    files = {name: _verify_artifact(bundle_root, binding, name) for name, binding in artifacts.items()}
    payloads: dict[str, dict[str, Any]] = {}
    for name in ("geometry", "control", "evaluator", "source_receipts"):
        payload = json.loads(files[name].read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise PortableBundleError(f"{name} sidecar must contain an object")
        payloads[name] = payload
        _walk_json_strings(payload, name, denied)
    expected_sidecar_schemas = {
        "geometry": "ds-data-02.m2.geometry.v1",
        "control": "ds-data-02.m2.control.v1",
        "evaluator": "ds-data-02.m2.no-model-evaluator.v2",
        "source_receipts": "ds-data-02.m2.source-receipts.v1",
    }
    for name, expected_schema in expected_sidecar_schemas.items():
        if payloads[name].get("schema") != expected_schema:
            raise PortableBundleError(f"{name} sidecar has an unexpected schema")
    if not isinstance(payloads["geometry"].get("geometry"), dict) or not payloads["geometry"].get("coordinate_frame"):
        raise PortableBundleError("geometry sidecar lacks actual geometry or coordinate-frame evidence")
    if not isinstance(payloads["control"].get("event_window"), dict):
        raise PortableBundleError("control sidecar lacks event-window evidence")
    receipts = payloads["source_receipts"]
    if not receipts.get("owner_metadata", {}).get("available"):
        raise PortableBundleError("owner metadata was not read while building the portable bundle")
    if not receipts.get("generated_xml", {}).get("available"):
        raise PortableBundleError("generated XML was not read while building the portable bundle")
    source_hdf5_receipt = receipts.get("source_hdf5")
    if not isinstance(source_hdf5_receipt, dict):
        raise PortableBundleError("source receipt lacks the bound source HDF5")
    source_bytes = source_hdf5_receipt.get("bytes")
    source_hash = source_hdf5_receipt.get("sha256")
    report_source_hash = source_hdf5_receipt.get("report_output_sha256")
    if (
        type(source_bytes) is not int
        or source_bytes <= 0
        or not isinstance(source_hash, str)
        or not _SHA256.fullmatch(source_hash)
        or not isinstance(report_source_hash, str)
        or not _SHA256.fullmatch(report_source_hash)
        or source_hash != report_source_hash
        or source_hdf5_receipt.get("matches_conversion_report") is not True
    ):
        raise PortableBundleError("source HDF5 receipt is not bound to conversion output_sha256")
    manifest_source_evidence = manifest.get("source_evidence")
    if not isinstance(manifest_source_evidence, dict) or manifest_source_evidence.get("source_hdf5") != source_hdf5_receipt:
        raise PortableBundleError("manifest source evidence disagrees with source HDF5 receipt")
    trajectory_summary = _validate_trajectory(
        files["trajectory"], case_id, require_complete=True, denied=denied
    )
    label_summary = _validate_labels(files["labels"], files["trajectory"], denied=denied)
    if label_summary["particles"] != trajectory_summary["particles"]:
        raise PortableBundleError("label particle_count does not match trajectory")
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
    recomputed_evaluator = _evaluator_score(files["trajectory"], files["labels"])
    if evaluator.get("schema") != "ds-data-02.m2.no-model-evaluator.v2" or not evaluator.get("passed"):
        raise PortableBundleError("no-model evaluator did not pass self/negative checks")
    for key in (
        "label_recompute_max_abs_m",
        "identity_permutation_rmse_m",
        "field_perturbation_delta_m",
    ):
        if not np.isclose(float(evaluator.get(key, np.nan)), float(recomputed_evaluator[key]), rtol=0.0, atol=1e-12):
            raise PortableBundleError(f"stored evaluator score does not match recomputed {key}")
    if evaluator.get("region_mismatch_count") != recomputed_evaluator["region_mismatch_count"]:
        raise PortableBundleError("stored evaluator region score does not match recomputation")
    if evaluator.get("transport_summary") != recomputed_evaluator["transport_summary"]:
        raise PortableBundleError("stored evaluator transport summary does not match recomputation")
    if evaluator.get("checks") != recomputed_evaluator["checks"] or evaluator.get("passed") != recomputed_evaluator["passed"]:
        raise PortableBundleError("stored evaluator checks do not match recomputation")
    return {
        "schema": "ds-data-02.m2.portable-bundle-validation.v1",
        "case_id": case_id,
        "trajectory": trajectory_summary,
        "labels": label_summary,
        "integrity": {"bytes": integrity["bytes"], "sha256": integrity["sha256"]},
        "frame_checks": frame_checks,
        "evaluator": recomputed_evaluator,
        "portable": True,
        "original_paths_denied": True,
        "denied_probe_paths": [str(path) for path in denied_probe_paths],
        "denied_probe_passed": True,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="sanitize an existing direct-conversion HDF5")
    build.add_argument("--source-hdf5", required=True, type=Path)
    build.add_argument("--source-report", required=True, type=Path)
    build.add_argument("--output-root", required=True, type=Path)
    build.add_argument("--case-id", required=True)
    build.add_argument(
        "--owner-metadata",
        type=Path,
        help="optional exact owner metadata file to bind while building",
    )
    build.add_argument(
        "--generated-xml",
        type=Path,
        help="optional exact generated XML file to bind while building",
    )
    validate = sub.add_parser("validate", help="validate a relocated portable bundle")
    validate.add_argument("--bundle-root", required=True, type=Path)
    validate.add_argument(
        "--probe-denied-path",
        action="append",
        default=[],
        type=Path,
        help="path that must be inaccessible in the validation namespace",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = (
            build_bundle(
                args.source_hdf5,
                args.source_report,
                args.output_root,
                args.case_id,
                owner_metadata=args.owner_metadata,
                generated_xml=args.generated_xml,
            )
            if args.command == "build"
            else validate_bundle(args.bundle_root, denied_probe_paths=tuple(args.probe_denied_path))
        )
        print(json.dumps(result, indent=2, sort_keys=True))
    except (OSError, ValueError, KeyError, PortableBundleError) as exc:
        print(f"portable-bundle: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
