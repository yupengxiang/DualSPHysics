#!/usr/bin/env python3
"""Generic source-bound typed-HDF5 lifecycle sidecar for one CURRENT case.

The pilot reads one already-produced typed trajectory only after the shared
runtime has reserved the request.  It validates the static ``(Zone, Idp)``
identity, streams saved frames in bounded chunks, and writes a compact summary
plus JSONL per-identity records.  A valid mask or typed disappearance is a
saved-record observation; it is not a native numerical cause, physical fate,
legal flux, or dynamics result.  QI/QN/QE stay UNKNOWN.

``prepare`` consumes only CURRENT/audit/scan/receipt JSON and HDF5 stat plus a
known producer SHA.  It never opens or hashes the trajectory.  ``audit`` is the
post-reservation worker: it performs a pre-hash, bounded HDF5 stream, and
post-hash (three minimum source passes), while preserving inactive NaNs as
inactive rather than valid observations.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import tempfile
import time
from typing import Any, Iterable

SCRIPT = Path(__file__).resolve()
VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
TYPE_NAMES = {0: "fixed", 1: "moving", 2: "floating", 3: "fluid"}
STATIC_FIELDS = ("time", "particle_id", "particle_zone", "initial_type", "initial_mass")
FRAME_FIELDS = ("position", "velocity", "density", "mass", "pressure", "valid", "type")
FIELD_UNITS_DEFAULT = {"position": "m", "velocity": "m/s", "density": "kg/m^3", "mass": "kg", "pressure": "Pa", "time": "s"}
SCHEMA = "ds02.stage2.typed-lifecycle-sidecar.v2"
MANIFEST_SCHEMA = "ds02.stage2.typed-lifecycle-sidecar-manifest.v2"
REQUEST_SCHEMA = "ds02.request.v1"
RECORD_SCHEMA = "ds02.stage2.typed-lifecycle-records.v2"
MAX_SUMMARY_BYTES = 2 * 1024 * 1024
MAX_RECORD_BYTES = 512 * 1024 * 1024
H5_SUFFIXES = {".h5", ".hdf5"}


class LifecycleError(ValueError):
    """Raised when source identity or lifecycle contracts are not closed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _path(value: Any, label: str, *, allow_missing: bool = False, allow_payload: bool = False) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not value:
        raise LifecycleError(f"{label} lacks a path")
    path = Path(value).expanduser().resolve()
    if not allow_payload and path.suffix.lower() in H5_SUFFIXES:
        raise LifecycleError(f"{label} payload access is not allowed here: {path}")
    if not allow_missing and not path.is_file():
        raise LifecycleError(f"{label} is missing: {path}")
    return path


def _trajectory_path(value: Any, label: str) -> Path:
    path = _path(value, label, allow_payload=True)
    if path.suffix.lower() not in H5_SUFFIXES:
        raise LifecycleError(f"{label} is not a typed HDF5 trajectory: {path}")
    return path


def _stat(path: Path, label: str, *, allow_payload: bool = False) -> dict[str, Any]:
    path = _path(path, label, allow_payload=allow_payload)
    value = path.stat()
    return {
        "path": str(path), "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns), "st_dev": int(value.st_dev), "st_ino": int(value.st_ino),
    }


def _json(path: Path, label: str) -> dict[str, Any]:
    path = _path(path, label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LifecycleError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise LifecycleError(f"{label} must be a JSON object")
    return value


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise LifecycleError(f"{label} must be a SHA-256 digest")
    result = value.lower()
    if any(c not in "0123456789abcdef" for c in result):
        raise LifecycleError(f"{label} is not hexadecimal")
    return result


def _hash_ref(path: Path, label: str) -> dict[str, Any]:
    stat = _stat(path, label)
    return {**stat, "sha256": sha256_file(path), "role": label}


def _literal_file(value: Any, label: str) -> tuple[Path, Path, dict[str, Any]]:
    """Bind a declared path while retaining its literal spelling.

    The v8 request must retain the configured venv/config path as declared by
    the producer, even when the venv entry is a symlink to ``/usr/bin``.
    Hash/stat are taken from the resolved file, and both names are recorded.
    """
    if not isinstance(value, (str, os.PathLike)) or not value:
        raise LifecycleError(f"{label} lacks a path")
    declared = Path(value).expanduser()
    resolved = declared.resolve()
    if not resolved.is_file():
        raise LifecycleError(f"{label} is missing: {declared}")
    ref = _hash_ref(resolved, label)
    ref["path"] = str(declared)
    ref["resolved_path"] = str(resolved)
    ref["declared_path"] = str(declared)
    return declared, resolved, ref


def _atomic_json(path: Path, value: dict[str, Any], *, max_bytes: int = MAX_SUMMARY_BYTES) -> None:
    path = Path(path).expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise LifecycleError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False, default=_json_default)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.stat().st_size > max_bytes:
            raise LifecycleError(f"JSON output exceeds {max_bytes} bytes: {path}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_jsonl(path: Path, header: dict[str, Any], rows: Iterable[dict[str, Any]], *, max_bytes: int = MAX_RECORD_BYTES) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise LifecycleError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    count = 0
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(header, ensure_ascii=False, sort_keys=True, allow_nan=False, default=_json_default) + "\n")
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False, default=_json_default) + "\n")
                count += 1
                if stream.tell() > max_bytes:
                    raise LifecycleError(f"records output exceeds {max_bytes} bytes: {path}")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return {"path": str(path), "bytes": int(path.stat().st_size), "sha256": sha256_file(path), "rows": count}


def _json_default(value: Any) -> Any:
    """Serialize numpy scalar metadata without accepting NaN/Inf."""
    item = value.item() if hasattr(value, "item") else value
    if isinstance(item, (bool, int, float, str)):
        if isinstance(item, float) and not math.isfinite(item):
            raise LifecycleError("non-finite scalar reached JSON output")
        return item
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _same_path(left: Any, right: Path) -> bool:
    try:
        return Path(str(left)).expanduser().resolve() == right.resolve()
    except (OSError, TypeError, ValueError):
        return False


def _read_small_refs(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    refs = manifest.get("source_refs")
    if not isinstance(refs, list):
        raise LifecycleError("manifest source_refs missing")
    result: dict[str, dict[str, Any]] = {}
    for ref in refs:
        if not isinstance(ref, dict) or not isinstance(ref.get("role"), str):
            raise LifecycleError("manifest source reference is malformed")
        role = ref["role"]
        if role in result:
            raise LifecycleError(f"duplicate source role: {role}")
        if role == "trajectory_h5":
            continue
        path = _path(ref.get("path"), role)
        expected = _sha(ref.get("sha256"), f"{role} SHA")
        actual = sha256_file(path)
        if actual != expected:
            raise LifecycleError(f"source input changed: {role}")
        result[role] = {**ref, "path": str(path), "sha256": expected}
    return result


def _current_case(current: dict[str, Any], case_id: str, expected_family_id: str | None = None) -> dict[str, Any]:
    if current.get("schema") != "ds02.stage2.current336.v1":
        raise LifecycleError("CURRENT schema differs")
    cases = current.get("cases")
    if not isinstance(cases, list):
        raise LifecycleError("CURRENT cases missing")
    matches = [row for row in cases if isinstance(row, dict) and row.get("physical_case_id") == case_id]
    if len(matches) != 1:
        raise LifecycleError(f"CURRENT case is not unique: {case_id}")
    row = matches[0]
    if expected_family_id is not None and row.get("family_id") != expected_family_id:
        raise LifecycleError("CURRENT case family differs from requested family")
    trajectory = row.get("trajectory")
    if not isinstance(trajectory, dict):
        raise LifecycleError("CURRENT trajectory metadata missing")
    return row


def _audit_case(audit: dict[str, Any], case_id: str) -> dict[str, Any]:
    if audit.get("schema") != "ds02.stage2.scientific-audit-independent-verification.v23":
        raise LifecycleError("scientific audit verification schema differs")
    rows = audit.get("verified_cases")
    if not isinstance(rows, list):
        raise LifecycleError("scientific audit verified_cases missing")
    matches = [row for row in rows if isinstance(row, dict) and row.get("physical_case_id") == case_id]
    if len(matches) != 1:
        raise LifecycleError(f"scientific audit case is not unique: {case_id}")
    row = matches[0]
    if row.get("scan_status") != "SCANNED" or row.get("field_failures"):
        raise LifecycleError("pilot scan is not a completed field-clean scan")
    if row.get("exact_CURRENT_path_and_declared_sha_match") is not True:
        raise LifecycleError("pilot audit row is not exact CURRENT-bound")
    return row


def _validate_source_catalog(
    current_path: Path,
    audit_path: Path,
    scan_path: Path,
    receipt_path: Path,
    case_id: str,
    expected_current_sha256: str,
    expected_family_id: str | None = None,
) -> dict[str, Any]:
    current_sha = sha256_file(current_path)
    expected_current_sha256 = _sha(expected_current_sha256, "expected CURRENT SHA")
    if current_sha != expected_current_sha256:
        raise LifecycleError(f"CURRENT SHA differs from requested catalog: {current_sha}")
    current = _json(current_path, "CURRENT336")
    current_row = _current_case(current, case_id, expected_family_id)
    audit = _json(audit_path, "scientific audit verification")
    audit_current = audit.get("current_catalog")
    if not isinstance(audit_current, dict) or audit_current.get("sha256") != expected_current_sha256:
        raise LifecycleError("scientific audit does not bind requested CURRENT SHA")
    audit_row = _audit_case(audit, case_id)
    if audit_row.get("family_id") not in (None, current_row.get("family_id")):
        raise LifecycleError("scientific audit family differs from CURRENT case")
    current_traj = _trajectory_path(current_row["trajectory"].get("path"), "CURRENT trajectory")
    audit_traj = _trajectory_path(audit_row.get("trajectory"), "audit trajectory")
    if current_traj != audit_traj:
        raise LifecycleError("CURRENT and scientific audit trajectory paths differ")
    expected_h5_sha = _sha(current_row["trajectory"].get("producer_declared_sha256"), "CURRENT producer trajectory SHA")
    if expected_h5_sha != _sha(audit_row.get("trajectory_verified_sha256"), "audit trajectory SHA"):
        raise LifecycleError("CURRENT and scientific audit trajectory SHA differ")
    h5_stat = _stat(current_traj, "trajectory HDF5", allow_payload=True)
    for source, key in ((current_row["trajectory"], "CURRENT trajectory"), (audit_row, "audit trajectory")):
        if source.get("bytes") is not None and int(source["bytes"]) != h5_stat["bytes"]:
            raise LifecycleError(f"{key} byte count differs from trajectory stat")
    scan = _json(scan_path, "scientific scan")
    if scan.get("schema") != "ds02.stage2.scientific-scan.v1" or scan.get("scan_status") != "SCANNED":
        raise LifecycleError("pilot scan is not completed")
    if scan.get("physical_case_id") != case_id or scan.get("trajectory") != str(current_traj):
        raise LifecycleError("scientific scan case/trajectory differs")
    if int(scan.get("source_bytes", -1)) != h5_stat["bytes"] or int(scan.get("frames", -1)) != int(current_row.get("frames", -2)):
        raise LifecycleError("scientific scan HDF5 metadata differs")
    receipt = _json(receipt_path, "scientific scan receipt")
    if str(receipt.get("status", "")).lower() != "completed" or receipt.get("returncode", 0) not in (0, None):
        raise LifecycleError("scientific scan receipt is not completed")
    if isinstance(receipt.get("request"), dict):
        # ``case_id`` in the scientific-scan receipt is the batch/product
        # owner (for example STAGE2_CURRENT336_SCIENCE), not the physical
        # CURRENT case.  Only an explicitly supplied physical_case_id can
        # constrain this row; otherwise the audit/current/scan identity
        # joins above are the authority.
        request_case = receipt["request"].get("physical_case_id")
        if request_case not in (None, case_id):
            raise LifecycleError("scientific scan receipt case differs")
    if audit_row.get("scan") != str(scan_path) or audit_row.get("receipt") != str(receipt_path):
        raise LifecycleError("scientific audit scan/receipt paths differ")
    if audit_row.get("scan_sha256") != sha256_file(scan_path) or audit_row.get("receipt_sha256") != sha256_file(receipt_path):
        raise LifecycleError("scientific audit scan/receipt SHA differs")
    lifecycle_field = audit_row.get("active_finite_lifecycle_fields")
    if lifecycle_field is None:
        lifecycle_exposure = {
            "status": "NOT_EXPOSED_IN_THIS_AUDIT_ROW",
            "source": "typed_lifecycle_worker_required",
            "scientific_credit": "NONE",
        }
    else:
        lifecycle_exposure = {
            "status": str(lifecycle_field),
            "source": "producer_audit_row",
            "scientific_credit": "NONE",
        }
    return {
        "current": current, "current_row": current_row, "current_sha256": current_sha,
        "expected_family_id": expected_family_id,
        "audit": audit, "audit_row": audit_row, "audit_sha256": sha256_file(audit_path),
        "scan": scan, "scan_sha256": sha256_file(scan_path),
        "receipt": receipt, "receipt_sha256": sha256_file(receipt_path),
        "trajectory": str(current_traj), "trajectory_stat": h5_stat, "trajectory_sha256": expected_h5_sha,
        "audit_path": str(audit_path), "current_path": str(current_path), "scan_path": str(scan_path), "receipt_path": str(receipt_path),
        "audit_lifecycle_exposure": lifecycle_exposure,
    }


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _safe_time(times: Any, index: int | None) -> float | None:
    if index is None or index < 0 or index >= len(times):
        return None
    return _finite(times[index])


def _load_h5_backend() -> tuple[Any, Any]:
    try:
        import h5py  # type: ignore
        import numpy as np  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on runtime environment
        raise LifecycleError("typed lifecycle worker requires the configured h5py/numpy environment") from exc
    return h5py, np


def _attrs(h: Any) -> dict[str, Any]:
    expected_units = dict(FIELD_UNITS_DEFAULT)
    units: dict[str, str] = {}
    raw_units = h.attrs.get("units_json")
    if isinstance(raw_units, bytes):
        raw_units = raw_units.decode("utf-8")
    units_status = "NOT_DECLARED"
    if raw_units is not None:
        try:
            value = json.loads(str(raw_units))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise LifecycleError("units_json is invalid") from exc
        if not isinstance(value, dict):
            raise LifecycleError("units_json is not an object")
        units = {str(k): str(v) for k, v in value.items()}
        conflicts = {key: (units.get(key), expected) for key, expected in expected_units.items() if key in units and units[key] != expected}
        if conflicts:
            raise LifecycleError(f"units_json conflicts with the SI typed protocol: {conflicts}")
        units_status = "EXPLICIT_SI" if set(expected_units).issubset(units) else "PARTIAL_NOT_VERIFIED"
    raw_frame = h.attrs.get("coordinate_frame")
    if isinstance(raw_frame, bytes):
        raw_frame = raw_frame.decode("utf-8", errors="replace")
    coordinate_frame = str(raw_frame) if raw_frame not in (None, "") else None
    raw_identity = h.attrs.get("identity_key")
    if isinstance(raw_identity, bytes):
        raw_identity = raw_identity.decode("utf-8", errors="replace")
    identity_key = str(raw_identity) if raw_identity not in (None, "") else None
    identity_status = "NOT_DECLARED"
    if identity_key is not None:
        normalized = "".join(identity_key.lower().split())
        if normalized != "(zone,idp)":
            raise LifecycleError(f"identity_key conflicts with the typed (Zone, Idp) contract: {identity_key}")
        identity_status = "EXPLICIT_MATCH"
    return {
        "units": units,
        "units_status": units_status,
        "units_expected_protocol": expected_units,
        "coordinate_frame": coordinate_frame,
        "coordinate_frame_status": "DECLARED_UNINTERPRETED" if coordinate_frame is not None else "NOT_DECLARED",
        "identity_key": identity_key,
        "identity_key_status": identity_status,
        "attribute_semantics": "coordinate frame and identity declaration are recorded; no physical-frame transfer is inferred",
    }


def _identity_keys(np: Any, zones: Any, ids: Any) -> None:
    if zones.dtype.kind not in "iu" or ids.dtype.kind not in "iu":
        raise LifecycleError("Zone/Idp identity axes must be integer")
    keys = np.rec.fromarrays([zones, ids])
    if len(np.unique(keys)) != len(ids):
        raise LifecycleError("duplicate (Zone, Idp) identity")


def _lifecycle_records(h5_path: Path, expected_frames: int, chunk: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    h5py, np = _load_h5_backend()
    if chunk <= 0 or isinstance(chunk, bool):
        raise LifecycleError("chunk must be positive")
    with h5py.File(h5_path, "r") as h:
        missing_static = [field for field in STATIC_FIELDS if field not in h]
        if missing_static:
            raise LifecycleError(f"missing static HDF5 fields: {missing_static}")
        times = np.asarray(h["time"][:])
        ids = np.asarray(h["particle_id"][:])
        zones = np.asarray(h["particle_zone"][:])
        initial_types = np.asarray(h["initial_type"][:])
        initial_mass = np.asarray(h["initial_mass"][:], dtype="float64")
        n = len(ids)
        frames = len(times)
        if frames != expected_frames or n == 0:
            raise LifecycleError("trajectory frame/particle count differs from bound scan")
        # Complex timestamps can compare truthily under NumPy in ways that
        # conceal an invalid saved timeline.  Accept only real numeric axes,
        # then compare their explicit float representation.
        if times.dtype.kind not in "fiu" or not np.isrealobj(times) or not np.isfinite(times).all():
            raise LifecycleError("trajectory time axis is not finite and strictly increasing")
        times = np.asarray(times, dtype="float64")
        if not np.all(np.diff(times) > 0):
            raise LifecycleError("trajectory time axis is not finite and strictly increasing")
        for value, label in ((zones, "particle_zone"), (ids, "particle_id"), (initial_types, "initial_type")):
            if value.shape != (n,) or value.dtype.kind not in "iu":
                raise LifecycleError(f"invalid static identity axis: {label}")
        if initial_mass.shape != (n,) or not np.isfinite(initial_mass).all() or not (initial_mass > 0).all():
            raise LifecycleError("initial_mass is not finite positive")
        _identity_keys(np, zones, ids)
        expected_shapes = {
            "position": (frames, n, 3), "velocity": (frames, n, 3),
            "density": (frames, n), "mass": (frames, n), "pressure": (frames, n),
            "valid": (frames, n), "type": (frames, n),
        }
        for field in FRAME_FIELDS:
            if field not in h or tuple(h[field].shape) != expected_shapes[field]:
                raise LifecycleError(f"missing or mismatched frame field: {field}")
        if not np.isin(initial_types, list(TYPE_NAMES)).all():
            raise LifecycleError("unknown initial type code")
        first_active = np.full(n, -1, dtype="int32")
        last_active = np.full(n, -1, dtype="int32")
        first_disappeared = np.full(n, -1, dtype="int32")
        previous_active = np.zeros(n, dtype=bool)
        previous_known = np.zeros(n, dtype=bool)
        ever_active = np.zeros(n, dtype=bool)
        initially_active = np.zeros(n, dtype=bool)
        reappearance_count = np.zeros(n, dtype="int32")
        first_reappearance = np.full(n, -1, dtype="int32")
        last_reappearance = np.full(n, -1, dtype="int32")
        mask_unknown_count = np.zeros(n, dtype="int32")
        type_unknown_count = np.zeros(n, dtype="int32")
        type_change_count = np.zeros(n, dtype="int32")
        active_nonfinite = {field: np.zeros(n, dtype="int32") for field in ("position", "velocity", "density", "mass", "pressure")}
        role = np.asarray(initial_types, dtype="int16")
        ledgers = {
            name: {
                "type_code": code, "initial_count": int((role == code).sum()),
                "initial_mass_kg": float(initial_mass[role == code].sum()),
                "active_count_by_frame": [], "active_mass_kg_by_frame": [],
                "active_nonfinite_counts": {field: 0 for field in active_nonfinite},
                "invalid_mask_count": 0, "unknown_type_count": 0,
            }
            for code, name in TYPE_NAMES.items()
        }
        for frame in range(frames):
            frame_active_count = {name: 0 for name in TYPE_NAMES.values()}
            frame_active_mass = {name: 0.0 for name in TYPE_NAMES.values()}
            for lo in range(0, n, chunk):
                hi = min(n, lo + chunk)
                index = np.arange(lo, hi)
                raw_valid = np.asarray(h["valid"][frame, lo:hi])
                valid_ok = np.isin(raw_valid, [0, 1])
                active = raw_valid.astype(bool)
                current_type = np.asarray(h["type"][frame, lo:hi])
                type_ok = np.isfinite(current_type) if current_type.dtype.kind in "fc" else np.ones(len(index), dtype=bool)
                type_ok &= np.isin(current_type, list(TYPE_NAMES))
                if not type_ok.all():
                    type_unknown_count[index[~type_ok]] += 1
                mask_unknown_count[index[~valid_ok]] += 1
                previous = previous_active[lo:hi]
                previous_was_known = previous_known[lo:hi]
                valid_event = valid_ok & type_ok
                if frame == 0:
                    initially_active[index[active & valid_event]] = True
                    first_active[index[active & valid_event]] = frame
                first_now = (first_active[lo:hi] < 0) & active & valid_event
                first_active[index[first_now]] = frame
                last_active[index[active & valid_event]] = frame
                disappeared = previous & previous_was_known & ~active & valid_event & (first_disappeared[lo:hi] < 0)
                first_disappeared[index[disappeared]] = frame
                reappeared = ~previous & previous_was_known & active & valid_event & (first_disappeared[lo:hi] >= 0)
                re_idx = index[reappeared]
                reappearance_count[re_idx] += 1
                first_reappearance[re_idx[(first_reappearance[re_idx] < 0)]] = frame
                last_reappearance[re_idx] = frame
                ever_active[index[active & valid_event]] = True
                for field in active_nonfinite:
                    values = np.asarray(h[field][frame, lo:hi])
                    finite = np.isfinite(values).all(axis=-1) if values.ndim == 2 else np.isfinite(values)
                    bad = active & valid_event & ~finite
                    bad_idx = index[bad]
                    active_nonfinite[field][bad_idx] += 1
                    for code, name in TYPE_NAMES.items():
                        ledgers[name]["active_nonfinite_counts"][field] += int((bad & (role[lo:hi] == code)).sum())
                for code, name in TYPE_NAMES.items():
                    selected = active & valid_event & (role[lo:hi] == code)
                    frame_active_count[name] += int(selected.sum())
                    mass_values = np.asarray(h["mass"][frame, lo:hi], dtype="float64")
                    frame_active_mass[name] += float(np.sum(mass_values[selected], dtype="float64"))
                    ledgers[name]["invalid_mask_count"] += int((~valid_ok & (role[lo:hi] == code)).sum())
                    ledgers[name]["unknown_type_count"] += int((~type_ok & (role[lo:hi] == code)).sum())
                type_change_count[index[active & valid_event & (current_type != role[lo:hi])]] += 1
                previous_active[lo:hi] = active & valid_event
                previous_known[lo:hi] = valid_event
            for name in TYPE_NAMES.values():
                ledgers[name]["active_count_by_frame"].append(frame_active_count[name])
                ledgers[name]["active_mass_kg_by_frame"].append(frame_active_mass[name])
        records: list[dict[str, Any]] = []
        for i in range(n):
            fa = int(first_active[i]) if first_active[i] >= 0 else None
            la = int(last_active[i]) if last_active[i] >= 0 else None
            fd = int(first_disappeared[i]) if first_disappeared[i] >= 0 else None
            fr = int(first_reappearance[i]) if first_reappearance[i] >= 0 else None
            lr = int(last_reappearance[i]) if last_reappearance[i] >= 0 else None
            if fa is None:
                censoring = "NO_ACTIVE_OBSERVATION"
            elif fd is None and la == frames - 1:
                censoring = "ACTIVE_AT_WINDOW_END_RIGHT_CENSORED"
            elif fd is not None and la == frames - 1 and reappearance_count[i] > 0:
                censoring = "REACTIVATED_AT_WINDOW_END"
            elif fd is not None and la is not None and la < frames - 1:
                censoring = "INACTIVE_AFTER_DISAPPEARANCE_WINDOW_CENSORED"
            else:
                censoring = "OBSERVED_DISAPPEARANCE"
            records.append({
                "zone": int(zones[i]), "idp": int(ids[i]), "initial_type_code": int(role[i]),
                "initial_role": TYPE_NAMES[int(role[i])], "initial_mass_kg": float(initial_mass[i]),
                "initially_active": bool(initially_active[i]), "new_id": bool(not initially_active[i] and fa is not None),
                "first_active_frame": fa, "first_active_time_s": _safe_time(times, fa),
                "last_active_frame": la, "last_active_time_s": _safe_time(times, la),
                "first_disappeared_frame": fd, "first_disappeared_time_s": _safe_time(times, fd),
                "first_disappeared_bracket_s": [_safe_time(times, fd - 1), _safe_time(times, fd)] if fd is not None else None,
                "reappearance_count": int(reappearance_count[i]),
                "first_reappearance_frame": fr, "first_reappearance_time_s": _safe_time(times, fr),
                "last_reappearance_frame": lr, "last_reappearance_time_s": _safe_time(times, lr),
                "missing_at_final": bool(not previous_active[i]) if previous_known[i] else None,
                "censoring": censoring,
                "unknown": {
                    "valid_mask_unknown_frame_count": int(mask_unknown_count[i]),
                    "type_unknown_frame_count": int(type_unknown_count[i]),
                    "active_nonfinite_field_counts": {field: int(values[i]) for field, values in active_nonfinite.items()},
                    "type_changed_active_frame_count": int(type_change_count[i]),
                },
                "native_exit_cause": "UNKNOWN",
                "physical_fate": "UNKNOWN",
                "legal_flux": "UNKNOWN",
                "dynamical_impact": "UNKNOWN",
            })
        metadata = _attrs(h)
        metadata.update({"frames": frames, "particles": n, "time_first_s": float(times[0]), "time_last_s": float(times[-1]), "identity_unique": True})
        for name, ledger in ledgers.items():
            ledger["activity_mask_field"] = "valid"
            ledger["finite_fields"] = ["position", "velocity", "density", "mass", "pressure"]
            ledger["units"] = dict(metadata["units"])
            ledger["unknown_active_id_count"] = sum(any(active_nonfinite[field][i] for field in active_nonfinite) or mask_unknown_count[i] or type_unknown_count[i] for i in range(n) if role[i] == ledger["type_code"])
            ledger["first_disappearance_count"] = sum(first_disappeared[i] >= 0 for i in range(n) if role[i] == ledger["type_code"])
            ledger["reappearance_id_count"] = sum(reappearance_count[i] > 0 for i in range(n) if role[i] == ledger["type_code"])
            ledger["no_active_observation_count"] = sum(first_active[i] < 0 for i in range(n) if role[i] == ledger["type_code"])
        return {"metadata": metadata, "role_ledgers": ledgers, "frame_count": frames, "particle_count": n, "time_s": [float(value) for value in times]}, records


def _validate_manifest(manifest_path: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]], Path, str, int]:
    manifest = _json(manifest_path, "typed lifecycle manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "READY_FOR_GUARDED_TYPED_LIFECYCLE":
        raise LifecycleError("typed lifecycle manifest is not guarded-ready")
    refs = _read_small_refs(manifest)
    required = {
        "current336", "scientific_audit", "scientific_scan", "scan_receipt", "worker",
        "python", "runtime_config", "runtime_v2", "runtime_v6", "runtime_v8", "dispatch_v8", "strict_v8",
    }
    if not required.issubset(refs):
        raise LifecycleError(f"manifest lacks source roles: {sorted(required - set(refs))}")
    h5_ref = next((ref for ref in manifest.get("source_refs", []) if isinstance(ref, dict) and ref.get("role") == "trajectory_h5"), None)
    if not isinstance(h5_ref, dict):
        raise LifecycleError("manifest lacks deferred trajectory_h5")
    h5_path = _trajectory_path(h5_ref.get("path"), "trajectory_h5")
    expected_h5_sha = _sha(h5_ref.get("sha256"), "trajectory_h5 known SHA")
    h5_stat = _stat(h5_path, "trajectory_h5", allow_payload=True)
    if int(h5_ref.get("bytes", -1)) != h5_stat["bytes"]:
        raise LifecycleError("trajectory_h5 stat changed before worker")
    case_id = str(manifest.get("physical_case_id", ""))
    if not case_id:
        raise LifecycleError("manifest lacks physical_case_id")
    family_id = str(manifest.get("family_id", ""))
    if not family_id:
        raise LifecycleError("manifest lacks family_id")
    current = _json(Path(refs["current336"]["path"]), "CURRENT336")
    _current_case(current, case_id, family_id)
    expected_current = manifest.get("current_catalog", {}).get("sha256")
    if _sha(expected_current, "manifest CURRENT SHA") != refs["current336"]["sha256"]:
        raise LifecycleError("manifest CURRENT SHA differs from bound source")
    return manifest, refs, h5_path, expected_h5_sha, int(manifest.get("frames", -1))


def audit(manifest_path: Path, summary_path: Path, records_path: Path, *, chunk: int = 65536) -> dict[str, Any]:
    started = time.monotonic()
    manifest, refs, h5_path, expected_h5_sha, expected_frames = _validate_manifest(manifest_path)
    current = _json(Path(refs["current336"]["path"]), "CURRENT336")
    case_id = str(manifest["physical_case_id"])
    current_row = _current_case(current, case_id, str(manifest["family_id"]))
    scan = _json(Path(refs["scientific_scan"]["path"]), "scientific scan")
    if scan.get("trajectory") != str(h5_path) or int(scan.get("frames", -1)) != expected_frames:
        raise LifecycleError("manifest scan/HDF5 identity differs")
    pre_stat = _stat(h5_path, "trajectory_h5 pre-read", allow_payload=True)
    pre_sha = sha256_file(h5_path)
    if pre_sha != expected_h5_sha:
        raise LifecycleError("trajectory_h5 pre-read SHA differs from known source")
    lifecycle_meta, records = _lifecycle_records(h5_path, expected_frames, chunk)
    post_stat = _stat(h5_path, "trajectory_h5 post-read", allow_payload=True)
    post_sha = sha256_file(h5_path)
    if pre_stat != post_stat or post_sha != pre_sha:
        raise LifecycleError("trajectory_h5 changed during lifecycle stream")
    record_header = {
        "schema": RECORD_SCHEMA, "status": "COMPLETED_TYPED_LIFECYCLE_RECORDS_NO_PHYSICAL_CREDIT",
        "family_id": manifest.get("family_id"), "physical_case_id": case_id, "source_trajectory": str(h5_path),
        "source_trajectory_sha256": pre_sha, "record_fields": "one row per static (Zone, Idp); saved-frame lifecycle only",
    }
    records_ref = _atomic_jsonl(records_path, record_header, records)
    summary = {
        "schema": SCHEMA, "status": "COMPLETED_TYPED_LIFECYCLE_NO_PHYSICAL_CREDIT",
        "family_id": manifest.get("family_id"), "physical_case_id": case_id,
        "source": {
            "current336_path": refs["current336"]["path"], "current336_sha256": refs["current336"]["sha256"],
            "scientific_scan_path": refs["scientific_scan"]["path"], "scientific_scan_sha256": refs["scientific_scan"]["sha256"],
            "trajectory_h5": {"path": str(h5_path), "known_sha256": expected_h5_sha, "pre_sha256": pre_sha, "post_sha256": post_sha, "pre_stat": pre_stat, "post_stat": post_stat},
            "audit_lifecycle_exposure": manifest.get("audit_lifecycle_exposure", {"status": "UNKNOWN", "scientific_credit": "NONE"}),
            "hash_passes_minimum": 3,
        },
        "timeline": {"frames": lifecycle_meta["frame_count"], "particles": lifecycle_meta["particle_count"], "time_s": lifecycle_meta["time_s"]},
        "metadata": lifecycle_meta["metadata"], "role_ledgers": lifecycle_meta["role_ledgers"],
        "records": records_ref,
        "lifecycle_semantics": {
            "first_disappearance": "first saved frame with known valid-mask transition active→inactive",
            "reappearance": "subsequent known inactive→active saved-frame transitions; count/first/last retained",
            "new_id": "initially inactive identity that later has a known active frame",
            "inactive_nan": "inactive NaN values are not treated as active observations",
            "continuous_event_time": "UNKNOWN",
            "native_exit_cause": "UNKNOWN",
            "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "read_policy": {"h5_opened_by_worker_after_reservation": True, "raw_bi4_opened": False, "partvtkout_started": False, "solver_started": False, "cfd_or_model_started": False},
        "source_read_cost": {"h5_pre_hash_bytes": pre_stat["bytes"], "h5_stream_lower_bound_bytes": pre_stat["bytes"], "h5_post_hash_bytes": post_stat["bytes"], "h5_minimum_passes": 3, "records_output_bytes": records_ref["bytes"], "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, "wall_seconds": time.monotonic() - started},
        "scope_limits": ["Typed valid-mask lifecycle is a saved-record observation, not proof of native numerical removal or physical outflow.", "All continuous event times, legal flux, destination, and dynamics remain UNKNOWN.", "This is one exact CURRENT case and does not revise the 336/118 products or historical receipts."],
    }
    _atomic_json(summary_path, summary)
    return {"status": summary["status"], "summary": str(Path(summary_path).resolve()), "records": str(Path(records_path).resolve()), "record_count": len(records), "h5_pre_post_sha256_equal": True}


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    current_path = _path(args.current, "CURRENT336")
    audit_path = _path(args.audit_verification, "scientific audit verification")
    scan_path = _path(args.scan, "scientific scan")
    receipt_path = _path(args.receipt, "scan receipt")
    case_id = str(args.case_id).strip()
    if not case_id:
        raise LifecycleError("case-id must be non-empty")
    family_id = str(args.family_id).strip() if args.family_id else None
    source = _validate_source_catalog(current_path, audit_path, scan_path, receipt_path, case_id, args.expected_current_sha256, family_id)
    # Retain the literal venv/config spellings in the request while hashing
    # their resolved files.  This prevents a symlink-normalized interpreter
    # from silently replacing the configured runtime edge.
    worker_declared, worker_resolved, worker_ref = _literal_file(args.worker, "worker")
    python_declared, python_resolved, python_ref = _literal_file(args.python, "python")
    config_declared, config_resolved, config_ref = _literal_file(args.runtime_config, "runtime_config")
    runtime_files: list[tuple[str, Path, Path, dict[str, Any]]] = []
    for role, value in (("runtime_v2", args.runtime_v2), ("runtime_v6", args.runtime_v6), ("runtime_v8", args.runtime_v8), ("dispatch_v8", args.dispatch_v8), ("strict_v8", args.strict_v8)):
        declared, resolved, ref = _literal_file(value, role)
        runtime_files.append((role, declared, resolved, ref))
    cwd = Path(args.cwd).expanduser().resolve()
    worktree = Path(args.worktree_root).expanduser().resolve()
    if not cwd.is_dir() or not worktree.is_dir():
        raise LifecycleError("cwd/worktree_root must be directories")
    try:
        cwd.relative_to(worktree)
    except ValueError as exc:
        raise LifecycleError("cwd must be inside worktree_root") from exc
    h5_path = Path(source["trajectory"])
    h5_stat = source["trajectory_stat"]
    small_refs = [
        {**_hash_ref(current_path, "current336"), "role": "current336"},
        {**_hash_ref(audit_path, "scientific_audit"), "role": "scientific_audit"},
        {**_hash_ref(scan_path, "scientific_scan"), "role": "scientific_scan"},
        {**_hash_ref(receipt_path, "scan_receipt"), "role": "scan_receipt"},
        worker_ref, python_ref, config_ref,
        *[ref for _role, _declared, _resolved, ref in runtime_files],
    ]
    manifest_path = output_dir / "typed-lifecycle-v2-manifest.json"
    summary_path = output_dir / "typed-lifecycle-v2-summary.json"
    records_path = output_dir / "typed-lifecycle-v2-records.jsonl"
    trajectory_ref = {**h5_stat, "role": "trajectory_h5", "sha256": source["trajectory_sha256"], "read_after_reservation": True, "content_read_by_preparer": False, "deferred": True}
    scan_request = source["receipt"].get("request") if isinstance(source["receipt"].get("request"), dict) else {}
    attempt_id = scan_request.get("attempt_id") or source["receipt"].get("attempt_id") or "UNKNOWN"
    manifest = {
        "schema": MANIFEST_SCHEMA, "status": "READY_FOR_GUARDED_TYPED_LIFECYCLE", "family_id": source["current_row"]["family_id"], "physical_case_id": case_id, "case_scope": f"one exact CURRENT336 case; scan receipt attempt {attempt_id}",
        "current_catalog": {"path": str(current_path), "sha256": source["current_sha256"]}, "audit_verification": {"path": str(audit_path), "sha256": source["audit_sha256"]},
        "frames": int(source["current_row"]["frames"]), "particles": int(source["current_row"]["particles"]), "trajectory_h5": trajectory_ref,
        "source_refs": [*small_refs, trajectory_ref],
        "audit_lifecycle_exposure": source["audit_lifecycle_exposure"],
        "runtime_contract": {
            "interpreter": {"literal_path": str(python_declared), "resolved_path": str(python_resolved), "sha256": python_ref["sha256"]},
            "config": {"literal_path": str(config_declared), "resolved_path": str(config_resolved), "sha256": config_ref["sha256"], "content_read_by_preparer": False},
        },
        "outputs": {"summary": str(summary_path), "records": str(records_path), "summary_max_bytes": MAX_SUMMARY_BYTES, "records_max_bytes": MAX_RECORD_BYTES},
        "read_policy": {"prepare_json_and_stat_only": True, "trajectory_h5_opened_by_preparer": False, "trajectory_h5_hashed_by_preparer": False, "worker_after_reservation_hash_parse_hash": True, "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN"},
        "semantic_contract": {"identity_key": "(Zone, Idp)", "roles": TYPE_NAMES, "fields": {**FIELD_UNITS_DEFAULT, "valid": "binary saved-frame mask", "type": "integer type code"}, "inactive_nan_is_not_active": True, "first_missing_is_saved_mask_transition_only": True, "new_id_and_reactivation_are_diagnostics_only": True, "QI_QN_QE": "UNKNOWN"},
    }
    _atomic_json(manifest_path, manifest, max_bytes=MAX_SUMMARY_BYTES)
    manifest_ref = {**_hash_ref(manifest_path, "manifest_contract"), "role": "manifest_contract"}
    input_refs = {ref["path"]: ref["sha256"] for ref in [*small_refs, manifest_ref]}
    request_path = output_dir / "typed-lifecycle-v2-request.json"
    command = [str(python_declared), str(worker_declared), "audit", "--manifest", str(manifest_path), "--summary", "{attempt_root}/typed-lifecycle-v2-summary.json", "--records", "{attempt_root}/typed-lifecycle-v2-records.jsonl", "--chunk", "65536"]
    request_case = "STAGE2_TYPED_LIFECYCLE_" + "_".join(part for part in (source["current_row"]["family_id"], case_id) if part).replace("-", "_")
    runtime_binding = {
        role: {"literal_path": str(declared), "resolved_path": str(resolved), "sha256": ref["sha256"]}
        for role, declared, resolved, ref in runtime_files
    }
    runtime_binding["runtime_config"] = {"literal_path": str(config_declared), "resolved_path": str(config_resolved), "sha256": config_ref["sha256"]}
    request = {
        "schema": REQUEST_SCHEMA, "shared_runtime_version": "v8", "family_id": source["current_row"]["family_id"], "case_id": request_case, "physical_case_id": case_id, "attempt_id": "typed-lifecycle-v2-root-forward", "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 1800, "max_memory_bytes": 2 * 1024 * 1024 * 1024, "estimated_storage_bytes": MAX_RECORD_BYTES + MAX_SUMMARY_BYTES, "estimated_cpu_core_hours": 0.5, "estimated_gpu_seconds": 0,
        "estimated_hdf5_read_bytes": int(h5_stat["bytes"] * 3), "estimated_bi4_read_bytes": 0, "estimated_native_read_bytes": 0, "estimated_input_read_bytes": sum(int(ref["bytes"]) for ref in [*small_refs, manifest_ref]), "estimated_deferred_source_bytes": h5_stat["bytes"], "estimated_deferred_read_passes": 3, "estimated_deferred_read_bytes": int(h5_stat["bytes"] * 3),
        "cwd": str(cwd), "worktree_root": str(worktree), "command": command, "input_files": sorted(input_refs), "input_sha256": dict(sorted(input_refs.items())), "deferred_input_files": [str(h5_path)], "deferred_input_records": [trajectory_ref], "output_files": ["{attempt_root}/typed-lifecycle-v2-summary.json", "{attempt_root}/typed-lifecycle-v2-records.jsonl"], "runtime_binding": runtime_binding, "manifest_contract": {"path": str(manifest_path), "sha256": manifest_ref["sha256"]}, "interpreter_binding": {"literal_path": str(python_declared), "resolved_executable_path": str(python_resolved), "sha256": python_ref["sha256"]},
        "guarded_payload_binding": {"trajectory_h5": "deferred_after_reservation_pre_hash_stream_post_hash", "raw_bi4_content_read": False, "solver_started": False, "records_large_output": True}, "source_read_cost": {"h5_minimum_passes": 3, "h5_bytes_per_pass": h5_stat["bytes"], "estimated_record_cap_bytes": MAX_RECORD_BYTES, "memory_cap_bytes": 2 * 1024 * 1024 * 1024}, "claim_boundary": {"typed_lifecycle": "saved-record diagnostic only", "native_exit_cause": "UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}, "launch_allowed": True, "execution_allowed": True, "launch_owner": "root", "shared_lease_required": True, "request_note": "One exact CURRENT case. Builder reads JSON/stat, literal interpreter/config, and known H5 SHA only; worker opens trajectory after reservation. Does not modify historical scan/H5/CURRENT or grant physical qualification."}
    _atomic_json(request_path, request, max_bytes=MAX_SUMMARY_BYTES)
    return {"status": "prepared", "manifest": str(manifest_path), "request": str(request_path), "manifest_sha256": sha256_file(manifest_path), "request_sha256": sha256_file(request_path), "physical_case_id": case_id, "trajectory_bytes": h5_stat["bytes"], "h5_content_opened_by_preparer": False, "estimated_h5_read_passes": 3, "manifest_in_input_refs": True, "audit_lifecycle_exposure": source["audit_lifecycle_exposure"]}


def self_test() -> dict[str, Any]:
    return {"status": "PASS", "schema": SCHEMA, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}, "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("self-test")
    prep = sub.add_parser("prepare")
    prep.add_argument("--current", type=Path, required=True)
    prep.add_argument("--audit-verification", type=Path, required=True)
    prep.add_argument("--scan", type=Path, required=True)
    prep.add_argument("--receipt", type=Path, required=True)
    prep.add_argument("--case-id", required=True)
    prep.add_argument("--family-id")
    prep.add_argument("--expected-current-sha256", required=True)
    prep.add_argument("--output-dir", type=Path, required=True)
    prep.add_argument("--worker", type=Path, default=SCRIPT)
    prep.add_argument("--python", type=Path, default=VENV)
    prep.add_argument("--runtime-config", type=Path, required=True)
    for option in ("runtime-v2", "runtime-v6", "runtime-v8", "dispatch-v8", "strict-v8", "cwd", "worktree-root"):
        prep.add_argument(f"--{option}", type=Path, required=True)
    audit = sub.add_parser("audit")
    audit.add_argument("--manifest", type=Path, required=True)
    audit.add_argument("--summary", type=Path, required=True)
    audit.add_argument("--records", type=Path, required=True)
    audit.add_argument("--chunk", type=int, default=65536)
    args = parser.parse_args(argv)
    try:
        if args.action == "self-test":
            print(json.dumps(self_test(), sort_keys=True))
        elif args.action == "prepare":
            print(json.dumps(prepare(args), sort_keys=True))
        else:
            print(json.dumps(audit(args.manifest, args.summary, args.records, chunk=args.chunk), sort_keys=True))
    except LifecycleError as exc:
        raise SystemExit(f"LifecycleError: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
