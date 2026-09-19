#!/usr/bin/env python3
"""B1R material-sidecar lineage and exact-axis contract.

This module is deliberately narrower than ``r5_f1_material_task.py``.  It
does not advect tracers and never starts GenCase or DualSPHysics.  It only
binds a finite-boundary sidecar to one completed canary attempt:

* the converted canary HDF5 and completed attempt must have the same case and
  attempt identifiers;
* the attempt must contain native ``PartOut_*.obi4`` evidence;
* the MkCells geometry must be the case-named geometry used to build the
  sidecar;
* the sidecar time axis must be byte-for-byte equal as canonical float64
  values to the canary HDF5 axis; and
* the sidecar must carry hashes for the HDF5, MkCells, PartOut manifest,
  geometry, and exact time axis.

There is intentionally no resampling, interpolation, nearest-frame lookup,
or overwrite path.  ``generate`` may create one new sidecar at a previously
non-existent output path; all existing inputs and experiment artifacts are
read-only.  The generated sidecar remains an evidence artifact, not a
material-transport qualification or receipt.

Examples (run from ``lagrangian-fluid-lab``)::

    .venv/bin/python scripts/l2_b1r_sidecar_contract.py preflight \
      --hdf5 campaigns/l2-multifamily/resume-c6b28c8/family-canaries/f1r/data/F1R_center_dp0075.h5 \
      --vtk campaigns/l2-multifamily/resume-c6b28c8/family-canaries/f1r/artifacts/F1R_center_dp0075/generated/F1R_center_dp0075_MkCells.vtk \
      --attempt-dir campaigns/l2-multifamily/runs/F1R_center_dp0075/attempts/<attempt>.complete

    .venv/bin/python scripts/l2_b1r_sidecar_contract.py generate \
      --hdf5 <same-canary.h5> --vtk <same-MkCells.vtk> \
      --attempt-dir <same-attempt.complete> --output <new-sidecar.h5>

The CLI returns ``2`` for a bounded contract rejection.  That is an
evidence decision, not a solver failure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import h5py
import numpy as np

try:  # package execution: ``python scripts/...`` from the lab root
    from scripts.boundary_sidecars import (
        audit_sidecar,
        boundary_triangles,
        build_world_series,
        read_binary_vtk_polydata,
        write_sidecar,
    )
except ModuleNotFoundError:  # pragma: no cover - direct module execution
    from boundary_sidecars import (  # type: ignore
        audit_sidecar,
        boundary_triangles,
        build_world_series,
        read_binary_vtk_polydata,
        write_sidecar,
    )


LAB = Path(__file__).resolve().parents[1]
DEFAULT_SPEC = LAB / "campaigns" / "v0.1-candidate" / "r5-f1-material-task" / "transport_spec.v1.json"
CONTRACT_SCHEMA = "l2r.b1r.material_sidecar_contract.v1"
SIDECAR_SCHEMA = "boundary-sidecar-v1"
EXPECTED_FAMILY = "F1"
EXACT_TIME_POLICY = "canonical_float64_array_equal_no_resampling"


class ContractViolation(ValueError):
    """Raised by a strict validate/generate operation after a bounded reject."""

    def __init__(self, report: Mapping[str, Any]):
        self.report = dict(report)
        codes = [str(item.get("code", "unknown")) for item in self.report.get("issues", [])]
        suffix = ", ".join(codes) if codes else "unspecified"
        super().__init__(f"B1R sidecar contract rejected: {suffix}")


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, np.ndarray) and value.ndim == 0:
        return _text(value.item())
    if isinstance(value, np.generic):
        return _text(value.item())
    return str(value)


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"cannot serialize {type(value)!r}")


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=_json_default).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_time_bytes(values: Sequence[float] | np.ndarray) -> bytes:
    # The explicit little-endian dtype makes the digest independent of host
    # byte order and rejects a changed time value even when it is within R5's
    # historical 1e-8 allclose tolerance.
    array = np.asarray(values, dtype="<f8")
    return np.ascontiguousarray(array).tobytes(order="C")


def time_axis_sha256(values: Sequence[float] | np.ndarray) -> str:
    return _sha256_bytes(_canonical_time_bytes(values))


def _issue(issues: list[dict[str, Any]], code: str, message: str, **details: Any) -> None:
    item: dict[str, Any] = {"code": code, "message": message}
    item.update(details)
    issues.append(item)


def _path(path: Path | str) -> Path:
    return Path(path).expanduser().resolve()


def _load_material_policy(spec_path: Path) -> dict[str, Any]:
    """Load only the frozen R5 wall policy; never change the spec."""
    with Path(spec_path).open("r", encoding="utf-8") as handle:
        spec = json.load(handle)
    if spec.get("spec_id") != "lagrangian-fluid.f1.single-obstacle.material-transport":
        raise ValueError("B1R requires the single-obstacle R5 material spec")
    if spec.get("case_family") != EXPECTED_FAMILY or spec.get("case_variant") != "single_obstacle":
        raise ValueError("B1R requires an F1 single-obstacle material spec")
    wall = spec.get("wall")
    roles = wall.get("component_roles") if isinstance(wall, Mapping) else None
    if not isinstance(roles, Mapping) or not roles:
        raise ValueError("R5 material spec has no wall component registry")
    try:
        components = {int(key) for key in roles}
    except (TypeError, ValueError) as error:
        raise ValueError("R5 wall component registry contains a non-integer label") from error
    return {
        "spec_id": spec["spec_id"],
        "version": spec.get("version"),
        "case_family": spec.get("case_family"),
        "case_variant": spec.get("case_variant"),
        "expected_components": sorted(components),
        "expected_triangle_type": 0,
        "coordinate_frame": (wall or {}).get("coordinate_frame", "world"),
    }


def _read_hdf5_metadata(path: Path) -> tuple[dict[str, Any], np.ndarray]:
    with h5py.File(path, "r") as handle:
        if "time" not in handle:
            raise ValueError("canary HDF5 is missing the time dataset")
        time = np.asarray(handle["time"][:], dtype=np.float64)
        metadata = {
            "case_id": _text(handle.attrs.get("case_id")),
            "attempt_id": _text(handle.attrs.get("attempt_id")),
            "family": _text(handle.attrs.get("family")),
            "schema_version": _text(handle.attrs.get("schema_version")),
            "solver": _text(handle.attrs.get("solver")),
        }
    if time.ndim != 1 or len(time) < 2:
        raise ValueError("canary HDF5 time must be a one-dimensional axis with at least two frames")
    if not np.all(np.isfinite(time)) or not np.all(np.diff(time) > 0.0):
        raise ValueError("canary HDF5 time must be finite and strictly increasing")
    metadata.update({
        "frame_count": int(len(time)),
        "time_start_s": float(time[0]),
        "time_end_s": float(time[-1]),
        "time_axis_sha256": time_axis_sha256(time),
    })
    return metadata, time


def _load_attempt(attempt_dir: Path) -> dict[str, Any]:
    attempt_dir = _path(attempt_dir)
    metadata_path = attempt_dir / "attempt.json"
    if not metadata_path.is_file():
        raise ValueError(f"completed attempt metadata is missing: {metadata_path}")
    with metadata_path.open("r", encoding="utf-8") as handle:
        metadata = json.load(handle)
    if metadata.get("status") != "completed" or int(metadata.get("returncode", 1)) != 0:
        raise ValueError("B1R requires a completed zero-returncode canary attempt")
    if not str(attempt_dir.name).endswith(".complete"):
        raise ValueError("B1R refuses a partial/non-final attempt directory")
    case_id = _text(metadata.get("case_id"))
    attempt_id = _text(metadata.get("attempt_id"))
    if not case_id or not attempt_id:
        raise ValueError("attempt metadata must declare case_id and attempt_id")
    partout = sorted((attempt_dir / "data").glob("PartOut_*.obi4"))
    if not partout:
        raise ValueError("completed canary attempt has no native PartOut_*.obi4 evidence")
    files = [
        {
            "path": str(item.relative_to(attempt_dir)),
            "bytes": int(item.stat().st_size),
            "sha256": _sha256_file(item),
        }
        for item in partout
    ]
    return {
        "path": str(attempt_dir),
        "metadata_path": str(metadata_path),
        "case_id": case_id,
        "attempt_id": attempt_id,
        "status": metadata.get("status"),
        "returncode": int(metadata.get("returncode", 0)),
        "partout_files": files,
        "partout_manifest_sha256": _sha256_bytes(_canonical_json(files)),
    }


def _axis_comparison(expected: np.ndarray, actual: np.ndarray) -> dict[str, Any]:
    expected = np.asarray(expected, dtype=np.float64)
    actual = np.asarray(actual, dtype=np.float64)
    result: dict[str, Any] = {
        "policy": EXACT_TIME_POLICY,
        "interpolation_applied": False,
        "expected_count": int(expected.size),
        "actual_count": int(actual.size),
        "expected_start_s": float(expected[0]) if expected.size else None,
        "expected_end_s": float(expected[-1]) if expected.size else None,
        "actual_start_s": float(actual[0]) if actual.size else None,
        "actual_end_s": float(actual[-1]) if actual.size else None,
        "expected_sha256": time_axis_sha256(expected),
        "actual_sha256": time_axis_sha256(actual),
    }
    if expected.shape != actual.shape:
        result.update({"shape_equal": False, "exact_equal": False, "first_mismatch": None, "max_abs_delta_s": None})
        return result
    equal = np.array_equal(expected, actual)
    delta = np.abs(expected - actual)
    mismatch = np.flatnonzero(expected != actual)
    result.update({
        "shape_equal": True,
        "exact_equal": bool(equal),
        "first_mismatch": int(mismatch[0]) if mismatch.size else None,
        "max_abs_delta_s": float(np.max(delta)) if delta.size else 0.0,
    })
    if mismatch.size:
        index = int(mismatch[0])
        result["first_mismatch_expected_s"] = float(expected[index])
        result["first_mismatch_actual_s"] = float(actual[index])
    return result


def _read_sidecar(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    summary = audit_sidecar(path)
    with h5py.File(path, "r") as handle:
        required = ("time", "triangles_world", "triangle_mk", "triangle_type", "triangle_component")
        missing = [name for name in required if name not in handle]
        if missing:
            raise ValueError(f"B1R sidecar is missing explicit contract datasets: {missing}")
        arrays = {
            "time": np.asarray(handle["time"][:], dtype=np.float64),
            "triangles_world": np.asarray(handle["triangles_world"][:], dtype=np.float64),
            "triangle_mk": np.asarray(handle["triangle_mk"][:], dtype=np.int64),
            "triangle_type": np.asarray(handle["triangle_type"][:], dtype=np.int8),
            "triangle_component": np.asarray(handle["triangle_component"][:], dtype=np.int64),
        }
        attrs = {str(key): _text(value) for key, value in handle.attrs.items()}
    return {"audit": summary, "attrs": attrs}, arrays


def _compare_geometry(expected: Mapping[str, Any], actual: Mapping[str, Any]) -> dict[str, Any]:
    expected_triangles = np.asarray(expected["triangles_world"])
    actual_triangles = np.asarray(actual["triangles_world"])
    result: dict[str, Any] = {
        "expected_shape": list(expected_triangles.shape),
        "actual_shape": list(actual_triangles.shape),
        "expected_source_geometry_sha256": expected.get("source_geometry_sha256"),
        "triangle_array_exact": False,
        "triangle_mk_exact": bool(np.array_equal(expected["triangle_mk"], actual["triangle_mk"])),
        "triangle_type_exact": bool(np.array_equal(expected["triangle_type"], actual["triangle_type"])),
        "triangle_component_exact": bool(np.array_equal(expected["triangle_mk"], actual["triangle_component"])),
    }
    if expected_triangles.shape == actual_triangles.shape:
        result["triangle_array_exact"] = bool(np.array_equal(expected_triangles, actual_triangles))
    result["exact_geometry_match"] = bool(
        result["triangle_array_exact"]
        and result["triangle_mk_exact"]
        and result["triangle_type_exact"]
        and result["triangle_component_exact"]
    )
    return result


def _source_name_matches(value: str | None, expected: Path) -> bool:
    if not value:
        return False
    candidate = Path(value)
    # Generated sidecars use absolute provenance; accepting a relative clone
    # path here is useful when a sidecar is copied between identical worktrees.
    return candidate.name == expected.name


def _base_report() -> dict[str, Any]:
    return {
        "schema": CONTRACT_SCHEMA,
        "status": "rejected",
        "decision": "bounded_sidecar_contract_rejection",
        "issues": [],
        "controls": {
            "solver_launched": False,
            "gencase_launched": False,
            "gpu_used": False,
            "inputs_read_only": True,
            "interpolation_applied": False,
            "resume_state_modified": False,
            "existing_experiment_files_modified": False,
        },
    }


def preflight(
    hdf5_path: Path,
    vtk_path: Path,
    attempt_dir: Path,
    *,
    sidecar_path: Path | None = None,
    case_id: str | None = None,
    spec_path: Path = DEFAULT_SPEC,
) -> dict[str, Any]:
    """Read-only inspect of a canary/attempt/MkCells/sidecar tuple."""
    hdf5_path = _path(hdf5_path)
    vtk_path = _path(vtk_path)
    attempt_dir = _path(attempt_dir)
    sidecar_path = _path(sidecar_path) if sidecar_path is not None else None
    report = _base_report()
    report["inputs"] = {
        "hdf5": str(hdf5_path),
        "mkcells_vtk": str(vtk_path),
        "attempt_dir": str(attempt_dir),
        "sidecar": str(sidecar_path) if sidecar_path is not None else None,
        "requested_case_id": case_id,
    }
    issues: list[dict[str, Any]] = report["issues"]

    metadata: dict[str, Any] = {}
    hdf5_time = np.empty(0, dtype=np.float64)
    if not hdf5_path.is_file():
        _issue(issues, "missing_hdf5", "canary HDF5 does not exist", path=str(hdf5_path))
    else:
        try:
            metadata, hdf5_time = _read_hdf5_metadata(hdf5_path)
        except (OSError, ValueError) as error:
            _issue(issues, "invalid_hdf5", str(error), path=str(hdf5_path))
    report["hdf5"] = {
        **metadata,
        "sha256": _sha256_file(hdf5_path) if hdf5_path.is_file() else None,
    }

    attempt: dict[str, Any] = {}
    try:
        attempt = _load_attempt(attempt_dir)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        _issue(issues, "invalid_attempt", str(error), path=str(attempt_dir))
    report["attempt"] = attempt

    expected_case = case_id or metadata.get("case_id") or attempt.get("case_id")
    report["expected_case_id"] = expected_case
    if not expected_case:
        _issue(issues, "missing_case_id", "no case_id is available from the request, HDF5, or attempt")
    for source, value in (
        ("requested case_id", case_id),
        ("HDF5 case_id", metadata.get("case_id")),
        ("attempt case_id", attempt.get("case_id")),
    ):
        if value is not None and expected_case is not None and str(value) != str(expected_case):
            _issue(issues, "case_id_mismatch", f"{source} {value!r} does not match expected case_id {expected_case!r}")
    if metadata.get("attempt_id") and attempt.get("attempt_id") and metadata["attempt_id"] != attempt["attempt_id"]:
        _issue(
            issues,
            "attempt_id_mismatch",
            "HDF5 attempt_id does not match the completed attempt directory",
            hdf5_attempt_id=metadata["attempt_id"],
            attempt_id=attempt["attempt_id"],
        )
    if metadata.get("family") != EXPECTED_FAMILY:
        _issue(
            issues,
            "family_not_f1",
            f"B1R material contract requires family {EXPECTED_FAMILY!r}",
            actual_family=metadata.get("family"),
        )

    if expected_case and vtk_path.name != f"{expected_case}_MkCells.vtk":
        _issue(
            issues,
            "mkcells_case_id_mismatch",
            "MkCells filename is not the exact case-named geometry",
            expected=f"{expected_case}_MkCells.vtk",
            actual=vtk_path.name,
        )

    policy: dict[str, Any] = {}
    try:
        policy = _load_material_policy(_path(spec_path))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        _issue(issues, "invalid_material_spec", str(error), path=str(_path(spec_path)))
    report["material_policy"] = policy

    expected_series: dict[str, Any] = {}
    parsed: dict[str, Any] = {}
    if not vtk_path.is_file():
        _issue(issues, "missing_mkcells", "MkCells VTK does not exist", path=str(vtk_path))
    elif hdf5_path.is_file() and hdf5_time.size:
        try:
            parsed = read_binary_vtk_polydata(vtk_path)
            triangles = boundary_triangles(parsed)
            expected_series = build_world_series(hdf5_path, parsed)
            actual_labels = set(int(value) for value in np.unique(triangles["mk"]))
            expected_labels = set(int(value) for value in policy.get("expected_components", ()))
            report["mkcells"] = {
                "sha256": _sha256_file(vtk_path),
                "point_count": int(len(parsed["points"])),
                "polygon_count": int(len(parsed["cells"])),
                "boundary_triangle_count": int(len(triangles["triangles"])),
                "boundary_component_labels": sorted(actual_labels),
                "boundary_triangle_types": sorted(int(value) for value in np.unique(triangles["type"])),
            }
            if expected_labels and actual_labels != expected_labels:
                _issue(
                    issues,
                    "boundary_component_mismatch",
                    "new MkCells boundary components do not match the frozen F1 material registry",
                    expected=sorted(expected_labels),
                    actual=sorted(actual_labels),
                )
            expected_type = policy.get("expected_triangle_type")
            if expected_type is not None and not np.all(triangles["type"] == int(expected_type)):
                _issue(
                    issues,
                    "boundary_type_mismatch",
                    "F1 material sidecar requires fixed Type 0 boundary triangles",
                    expected=int(expected_type),
                    actual=sorted(int(value) for value in np.unique(triangles["type"])),
                )
        except (OSError, ValueError) as error:
            _issue(issues, "invalid_mkcells", str(error), path=str(vtk_path))
    report["expected_geometry"] = {
        "source_geometry_sha256": expected_series.get("source_geometry_sha256"),
        "triangle_count": int(expected_series["triangles_world"].shape[1]) if expected_series else None,
        "frame_count": int(expected_series["time"].size) if expected_series else None,
    }

    if sidecar_path is not None:
        if not sidecar_path.is_file():
            _issue(issues, "missing_sidecar", "requested sidecar does not exist", path=str(sidecar_path))
        else:
            try:
                sidecar_meta, sidecar_arrays = _read_sidecar(sidecar_path)
                sidecar_attrs = sidecar_meta["attrs"]
                report["sidecar"] = {
                    "sha256": _sha256_file(sidecar_path),
                    "audit": sidecar_meta["audit"],
                    "attrs": sidecar_attrs,
                }
                if sidecar_attrs.get("schema_version") != SIDECAR_SCHEMA:
                    _issue(
                        issues,
                        "sidecar_schema_mismatch",
                        "sidecar schema is not boundary-sidecar-v1",
                        actual=sidecar_attrs.get("schema_version"),
                    )
                if sidecar_attrs.get("coordinate_frame") != policy.get("coordinate_frame", "world"):
                    _issue(
                        issues,
                        "sidecar_coordinate_frame_mismatch",
                        "sidecar coordinate frame is not the frozen world frame",
                        actual=sidecar_attrs.get("coordinate_frame"),
                    )
                if expected_case and sidecar_attrs.get("case_id") != str(expected_case):
                    _issue(
                        issues,
                        "sidecar_case_id_mismatch",
                        "sidecar case_id is not the exact new canary case_id",
                        expected=str(expected_case),
                        actual=sidecar_attrs.get("case_id"),
                    )
                if not _source_name_matches(sidecar_attrs.get("source_hdf5"), hdf5_path):
                    _issue(
                        issues,
                        "sidecar_hdf5_provenance_mismatch",
                        "sidecar source_hdf5 does not name the selected canary HDF5",
                        expected=hdf5_path.name,
                        actual=sidecar_attrs.get("source_hdf5"),
                    )
                if not _source_name_matches(sidecar_attrs.get("source_vtk"), vtk_path):
                    _issue(
                        issues,
                        "sidecar_mkcells_provenance_mismatch",
                        "sidecar source_vtk does not name the selected MkCells geometry",
                        expected=vtk_path.name,
                        actual=sidecar_attrs.get("source_vtk"),
                    )
                if metadata.get("attempt_id") and sidecar_attrs.get("source_attempt_id") != metadata["attempt_id"]:
                    _issue(
                        issues,
                        "sidecar_attempt_binding_missing_or_mismatch",
                        "sidecar is not bound to the selected canary attempt_id",
                        expected=metadata.get("attempt_id"),
                        actual=sidecar_attrs.get("source_attempt_id"),
                    )
                expected_hashes = {
                    "source_hdf5_sha256": report["hdf5"].get("sha256"),
                    "source_mkcells_sha256": report.get("mkcells", {}).get("sha256"),
                    "source_partout_manifest_sha256": attempt.get("partout_manifest_sha256"),
                    "source_geometry_sha256": expected_series.get("source_geometry_sha256"),
                    "time_axis_sha256": metadata.get("time_axis_sha256"),
                }
                for attr_name, expected_hash in expected_hashes.items():
                    if expected_hash and sidecar_attrs.get(attr_name) != expected_hash:
                        _issue(
                            issues,
                            f"sidecar_{attr_name}_mismatch",
                            f"sidecar {attr_name} is not the exact selected input fingerprint",
                            expected=expected_hash,
                            actual=sidecar_attrs.get(attr_name),
                        )
                if sidecar_attrs.get("material_sidecar_contract") != CONTRACT_SCHEMA:
                    _issue(
                        issues,
                        "sidecar_contract_metadata_missing_or_mismatch",
                        "sidecar was not generated under the B1R exact-lineage contract",
                        expected=CONTRACT_SCHEMA,
                        actual=sidecar_attrs.get("material_sidecar_contract"),
                    )
                if hdf5_time.size:
                    axis = _axis_comparison(hdf5_time, sidecar_arrays["time"])
                    report["time_axis"] = axis
                    if not axis["exact_equal"]:
                        _issue(
                            issues,
                            "time_axis_mismatch",
                            "sidecar and canary HDF5 time axes are not exact float64 matches; no interpolation is permitted",
                            comparison=axis,
                        )
                if expected_series:
                    geometry = _compare_geometry(expected_series, {
                        "triangles_world": sidecar_arrays["triangles_world"],
                        "triangle_mk": sidecar_arrays["triangle_mk"],
                        "triangle_type": sidecar_arrays["triangle_type"],
                        "triangle_component": sidecar_arrays["triangle_component"],
                    })
                    report["geometry"] = geometry
                    if not geometry["exact_geometry_match"]:
                        _issue(
                            issues,
                            "boundary_geometry_mismatch",
                            "sidecar finite triangles or labels do not exactly match the selected MkCells geometry",
                            comparison=geometry,
                        )
            except (OSError, ValueError) as error:
                _issue(issues, "invalid_sidecar", str(error), path=str(sidecar_path))
    else:
        report["sidecar"] = None

    report["checks"] = {
        "exact_time_axis_required": True,
        "time_axis_policy": EXACT_TIME_POLICY,
        "partout_lineage_required": True,
        "finite_geometry_required": True,
        "f1_fixed_components_required": policy.get("expected_components"),
    }
    if not issues:
        report["status"] = "pass"
        report["decision"] = "exact_canary_sidecar_pair_admitted_for_bounded_cpu_preflight"
    else:
        report["status"] = "rejected"
    return report


def _strict(report: dict[str, Any]) -> dict[str, Any]:
    if report.get("status") != "pass":
        raise ContractViolation(report)
    return report


def validate_sidecar(
    hdf5_path: Path,
    vtk_path: Path,
    attempt_dir: Path,
    sidecar_path: Path,
    *,
    case_id: str | None = None,
    spec_path: Path = DEFAULT_SPEC,
) -> dict[str, Any]:
    """Strictly validate an existing sidecar without writing any input."""
    return _strict(preflight(
        hdf5_path,
        vtk_path,
        attempt_dir,
        sidecar_path=sidecar_path,
        case_id=case_id,
        spec_path=spec_path,
    ))


def _annotate_generated_sidecar(
    sidecar_path: Path,
    *,
    hdf5_path: Path,
    vtk_path: Path,
    hdf5_sha256: str,
    vtk_sha256: str,
    attempt: Mapping[str, Any],
    geometry_sha256: str,
    time_sha256: str,
) -> None:
    """Add lineage attrs only to a newly-created sidecar output."""
    with h5py.File(sidecar_path, "r+") as handle:
        handle.attrs["material_sidecar_contract"] = CONTRACT_SCHEMA
        handle.attrs["source_hdf5"] = str(hdf5_path)
        handle.attrs["source_vtk"] = str(vtk_path)
        handle.attrs["source_hdf5_sha256"] = hdf5_sha256
        handle.attrs["source_mkcells_sha256"] = vtk_sha256
        handle.attrs["source_attempt_id"] = str(attempt["attempt_id"])
        handle.attrs["source_attempt_case_id"] = str(attempt["case_id"])
        handle.attrs["source_partout_manifest_sha256"] = str(attempt["partout_manifest_sha256"])
        handle.attrs["source_partout_files_json"] = json.dumps(
            attempt["partout_files"], sort_keys=True, separators=(",", ":")
        )
        handle.attrs["source_geometry_sha256"] = geometry_sha256
        handle.attrs["time_axis_sha256"] = time_sha256
        handle.attrs["time_axis_policy"] = EXACT_TIME_POLICY
        handle.attrs["solver_or_gpu_launched_by_contract"] = False


def generate_sidecar(
    hdf5_path: Path,
    vtk_path: Path,
    attempt_dir: Path,
    output_path: Path,
    *,
    case_id: str | None = None,
    spec_path: Path = DEFAULT_SPEC,
) -> dict[str, Any]:
    """Generate one new exact sidecar, then validate it strictly."""
    hdf5_path = _path(hdf5_path)
    vtk_path = _path(vtk_path)
    output_path = _path(output_path)
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite an existing sidecar: {output_path}")
    if output_path in {hdf5_path, vtk_path, _path(attempt_dir)}:
        raise ValueError("sidecar output must be a new path distinct from all inputs")
    baseline = _strict(preflight(
        hdf5_path,
        vtk_path,
        attempt_dir,
        case_id=case_id,
        spec_path=spec_path,
    ))
    attempt = baseline["attempt"]
    expected_case = str(baseline["expected_case_id"])
    parsed = read_binary_vtk_polydata(vtk_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        write_sidecar(
            output_path,
            expected_case,
            hdf5_path,
            parsed,
            source_vtk_label=str(vtk_path),
            source_hdf5_label=str(hdf5_path),
        )
        expected_series = build_world_series(hdf5_path, parsed)
        _annotate_generated_sidecar(
            output_path,
            hdf5_path=hdf5_path,
            vtk_path=vtk_path,
            hdf5_sha256=baseline["hdf5"]["sha256"],
            vtk_sha256=baseline["mkcells"]["sha256"],
            attempt=attempt,
            geometry_sha256=expected_series["source_geometry_sha256"],
            time_sha256=baseline["hdf5"]["time_axis_sha256"],
        )
        report = validate_sidecar(
            hdf5_path,
            vtk_path,
            attempt_dir,
            output_path,
            case_id=case_id,
            spec_path=spec_path,
        )
        report["generation"] = {
            "created": True,
            "output": str(output_path),
            "output_sha256": _sha256_file(output_path),
            "solver_or_gpu_started": False,
        }
        return report
    except Exception:
        # The path did not exist before this function and is owned by this
        # bounded operation.  Do not leave a partially validated artifact.
        if output_path.is_file():
            output_path.unlink()
        raise


def _add_common_arguments(parser: argparse.ArgumentParser, *, sidecar: bool = False) -> None:
    parser.add_argument("--hdf5", type=Path, required=True, help="converted canary HDF5")
    parser.add_argument("--vtk", type=Path, required=True, help="the same case-named *_MkCells.vtk")
    parser.add_argument("--attempt-dir", type=Path, required=True, help="completed attempt directory containing PartOut")
    parser.add_argument("--case-id", help="optional explicit case id; must equal the HDF5 and attempt case")
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC, help="frozen R5 F1 material spec")
    if sidecar:
        parser.add_argument("--sidecar", type=Path, required=True, help="existing sidecar to validate")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    preflight_parser = subparsers.add_parser("preflight", help="read-only bounded inspection")
    _add_common_arguments(preflight_parser)
    preflight_parser.add_argument("--sidecar", type=Path, help="optional existing sidecar to inspect")
    validate_parser = subparsers.add_parser("validate", help="strictly validate an existing sidecar")
    _add_common_arguments(validate_parser, sidecar=True)
    generate_parser = subparsers.add_parser("generate", help="create one new sidecar and strictly validate it")
    _add_common_arguments(generate_parser)
    generate_parser.add_argument("--output", type=Path, required=True, help="new non-existent sidecar output path")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        if args.command == "preflight":
            report = preflight(
                args.hdf5, args.vtk, args.attempt_dir,
                sidecar_path=args.sidecar,
                case_id=args.case_id,
                spec_path=args.spec,
            )
        elif args.command == "validate":
            report = validate_sidecar(
                args.hdf5, args.vtk, args.attempt_dir, args.sidecar,
                case_id=args.case_id,
                spec_path=args.spec,
            )
        else:
            report = generate_sidecar(
                args.hdf5, args.vtk, args.attempt_dir, args.output,
                case_id=args.case_id,
                spec_path=args.spec,
            )
    except ContractViolation as error:
        print(json.dumps(error.report, indent=2, sort_keys=True, default=_json_default))
        return 2
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"schema": CONTRACT_SCHEMA, "status": "error", "error": str(error)}, indent=2))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True, default=_json_default))
    return 0 if report.get("status") == "pass" else 2


if __name__ == "__main__":  # pragma: no cover - exercised through CLI smoke tests
    raise SystemExit(main())
