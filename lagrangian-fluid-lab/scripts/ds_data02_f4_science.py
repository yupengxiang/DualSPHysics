#!/usr/bin/env python3
"""Actual F4 Q-I lifecycle and reference-observation audit.

This module consumes already completed DS-DATA-02 F4 HDF5/solver artifacts. It
never launches GenCase or a solver and never edits an input HDF5, BI4, XML,
control, RunPARTs, or PartOut file.  The audit has four deliberately separate
parts:

* fixed typed-identity lifecycle accounting, joined to the native RunPARTs
  counters and an official PartVTKOut Motive record;
* fixed physical source-support interaction curves and finite-aperture
  transport labels;
* actual-time spatial and integrator/save comparisons with frozen budgets;
* point-cloud PNG/GIF previews whose downsampling is explicitly display-only.

The resulting evidence is Q-I/reference evidence.  It does not grant Q-N or
production eligibility.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import hashlib
import io
import json
import math
import os
from pathlib import Path
import resource
import subprocess
import time
from typing import Any, Iterable, Mapping, Sequence

import h5py
import numpy as np

try:
    from scipy.spatial import cKDTree
except Exception:  # pragma: no cover - the shared runner has scipy
    cKDTree = None  # type: ignore[assignment]


SCHEMA = "ds02.f4.science-audit.v2"
OPERATORS_SCHEMA = "ds02.f4.science-operators.v2"
MOTIVE_NAMES = {1: "position", 2: "density", 3: "movement"}
MACRO_ERROR_BUDGET = 0.05
EVENT_ERROR_BUDGET = 0.02
TEMPORAL_ITEM_ALLOCATION = 0.2
REQUIRED_H5 = (
    "time", "particle_id", "particle_zone", "initial_type", "initial_mk",
    "initial_mass", "valid", "type", "mk", "position", "velocity",
    "density", "mass",
)


class ScienceAuditError(RuntimeError):
    """Raised when a required evidence contract is malformed."""


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


def _json_value(value: Any) -> Any:
    return json.loads(json.dumps(value, default=_json_default))


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=_json_default).encode("utf-8")
    ).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _resource_snapshot() -> dict[str, float]:
    result: dict[str, float] = {}
    for who, label in ((resource.RUSAGE_SELF, "self"), (resource.RUSAGE_CHILDREN, "children")):
        usage = resource.getrusage(who)
        result[f"{label}_user_seconds"] = float(usage.ru_utime)
        result[f"{label}_system_seconds"] = float(usage.ru_stime)
        result[f"{label}_max_rss_kib"] = float(usage.ru_maxrss)
        result[f"{label}_minor_page_faults"] = float(usage.ru_minflt)
        result[f"{label}_major_page_faults"] = float(usage.ru_majflt)
    return result


def _resource_delta(before: Mapping[str, float], after: Mapping[str, float]) -> dict[str, float]:
    return {key: float(after[key] - before.get(key, 0.0)) for key in after}


def _load_json(path: Path) -> Any:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def _load_object(path: Path) -> dict[str, Any]:
    value = _load_json(path)
    if not isinstance(value, dict):
        raise ScienceAuditError(f"expected JSON object: {path}")
    return value


def _number(value: Any, default: float | None = None) -> float | None:
    if value is None or str(value).strip() == "":
        return default
    try:
        number = float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _integer(value: Any, default: int | None = None) -> int | None:
    number = _number(value)
    return default if number is None else int(number)


def _normalise_row(row: Mapping[Any, Any]) -> dict[str, Any]:
    return {str(key).strip().rstrip(","): value for key, value in row.items() if key is not None}


def _finite_vector(value: Any, size: int = 3) -> bool:
    try:
        array = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError):
        return False
    return array.shape == (size,) and bool(np.isfinite(array).all())


def _bounds(region: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    low = np.asarray(region["low_m"], dtype=np.float64)
    high = low + np.asarray(region["size_m"], dtype=np.float64)
    if low.shape != (3,) or high.shape != (3,) or not np.isfinite(low).all() or not np.isfinite(high).all() or np.any(high <= low):
        raise ScienceAuditError(f"invalid physical region: {region}")
    return low, high


def _inside(points: np.ndarray, low: np.ndarray, high: np.ndarray, tolerance: float = 0.0) -> np.ndarray:
    return np.all((points >= low - tolerance) & (points <= high + tolerance), axis=1)


def _event_from_flags(times: np.ndarray, flags: Sequence[bool]) -> dict[str, Any]:
    values = np.asarray(flags, dtype=bool)
    indices = np.flatnonzero(values)
    if indices.size == 0:
        return {"status": "right_censored", "time_s": None, "frame": None, "bracket_s": None}
    index = int(indices[0])
    if index == 0:
        bracket = [float(times[0]), float(times[0])]
    else:
        bracket = [float(times[index - 1]), float(times[index])]
    return {
        "status": "observed",
        "time_s": float(times[index]),
        "frame": index,
        "bracket_s": bracket,
    }


def _recontact_from_flags(times: np.ndarray, flags: Sequence[bool], first: Mapping[str, Any]) -> dict[str, Any]:
    first_frame = first.get("frame")
    if first_frame is None:
        return {"status": "right_censored", "time_s": None, "frame": None, "bracket_s": None}
    separated = False
    for index in range(int(first_frame) + 1, len(flags)):
        if not flags[index]:
            separated = True
        elif separated:
            return _event_from_flags(times, [False] * index + [True] + [False] * (len(flags) - index - 1))
    return {"status": "right_censored", "time_s": None, "frame": None, "bracket_s": None}


def _read_runparts(path: Path) -> dict[str, Any]:
    """Parse every native PART row, including interval exclusion counters."""

    result: dict[str, Any] = {
        "path": str(path),
        "sha256": sha256_file(path) if path.is_file() else None,
        "status": "missing" if not path.is_file() else "malformed",
        "rows": [],
        "totals": {"NpOut": 0, "NpOutPos": 0, "NpOutRho": 0, "NpOutMov": 0},
        "first_nonzero": {},
        "last": None,
    }
    if not path.is_file():
        return result
    lines = path.read_text(errors="replace").splitlines()
    header = next((index for index, line in enumerate(lines) if line.startswith("Part;")), None)
    if header is None:
        return result
    rows: list[dict[str, Any]] = []
    malformed = 0
    fields = ("NpOut", "NpOutPos", "NpOutRho", "NpOutMov")
    for raw in csv.DictReader(lines[header:], delimiter=";"):
        row = _normalise_row(raw)
        part = _integer(row.get("Part"))
        time_s = _number(row.get("TimeStep [s]"))
        if part is None or time_s is None:
            malformed += 1
            continue
        parsed = {field: _integer(row.get(field), 0) for field in fields}
        if any(value is None or value < 0 for value in parsed.values()):
            malformed += 1
            continue
        item = {
            "part": int(part),
            "time_s": float(time_s),
            **{field: int(parsed[field]) for field in fields},
            "NpSim": _integer(row.get("NpSim")),
            "NpfSim": _integer(row.get("NpfSim")),
            "NpNew": _integer(row.get("NpNew")),
            "NpSave": _integer(row.get("NpSave")),
        }
        rows.append(item)
        for field in fields:
            result["totals"][field] += item[field]
            if item[field] > 0 and field not in result["first_nonzero"]:
                result["first_nonzero"][field] = {"part": int(part), "time_s": float(time_s), "count": item[field]}
    result["rows"] = rows
    result["last"] = rows[-1] if rows else None
    result["malformed_rows"] = malformed
    result["status"] = "available" if malformed == 0 else "available_with_findings"
    result["row_count"] = len(rows)
    return result


def _partvtk_environment(binary: Path) -> dict[str, str]:
    env = os.environ.copy()
    directory = str(binary.parent)
    env["LD_LIBRARY_PATH"] = directory + ":" + env.get("LD_LIBRARY_PATH", "")
    return env


def run_partvtkout(*, binary: Path, data_dir: Path, output_dir: Path) -> dict[str, Any]:
    """Decode existing native PartOut into a new output directory only."""

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "PartOut.csv"
    resume_path = output_dir / "PartOut-resume.csv"
    stdout_path = output_dir / "PartVTKOut.stdout.log"
    command = [
        str(binary), "-dirdata", str(data_dir), "-savecsv", str(csv_path),
        "-saveresume", str(resume_path), "-createdirs:1", "-csvsep:1",
    ]
    process = subprocess.run(
        command, cwd=data_dir.parent, env=_partvtk_environment(binary),
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )
    stdout_path.write_text(process.stdout or "", encoding="utf-8")
    return {
        "status": "available" if process.returncode == 0 and csv_path.is_file() else "failed",
        "command": command,
        "returncode": int(process.returncode),
        "binary": str(binary),
        "binary_sha256": sha256_file(binary) if binary.is_file() else None,
        "data_dir": str(data_dir),
        "csv": str(csv_path),
        "csv_sha256": sha256_file(csv_path) if csv_path.is_file() else None,
        "resume": str(resume_path),
        "resume_sha256": sha256_file(resume_path) if resume_path.is_file() else None,
        "stdout": str(stdout_path),
        "stdout_sha256": sha256_file(stdout_path),
    }


def _parse_partvtk_csv(path: Path, runparts: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(path),
        "sha256": sha256_file(path) if path.is_file() else None,
        "status": "missing" if not path.is_file() else "malformed",
        "rows": [],
        "motive_counts": {},
        "duplicate_idp": [],
    }
    if not path.is_file():
        return result
    text = path.read_text(errors="replace")
    reader = csv.DictReader(text.splitlines(), delimiter=",")
    rows: list[dict[str, Any]] = []
    seen: dict[int, int] = {}
    malformed = 0
    for raw in reader:
        row = _normalise_row(raw)
        idp = _integer(row.get("Idp"))
        part = _integer(row.get("PartOut"))
        motive = _integer(row.get("Motive"))
        position = [_number(row.get(f"Pos.{axis} [m]")) for axis in "xyz"]
        density = _number(row.get("Rhop [kg/m^3]"))
        if idp is None or part is None or motive is None or any(x is None for x in position) or density is None:
            malformed += 1
            continue
        native = next((item for item in runparts.get("rows", []) if item["part"] == part), None)
        active_reasons = []
        if native is not None:
            for key, label in (("NpOutPos", "position"), ("NpOutRho", "density"), ("NpOutMov", "movement")):
                if native[key] > 0:
                    active_reasons.append(label)
        rows.append({
            "idp": int(idp),
            "zone": 0,
            "part_out": int(part),
            "motive_code": int(motive),
            "motive": MOTIVE_NAMES.get(int(motive), "unknown"),
            "position_m": [float(x) for x in position],
            "density_kg_m3": float(density),
            "native_reason": active_reasons[0] if len(active_reasons) == 1 else ("multiple" if active_reasons else "unknown"),
            "native_reason_counters": active_reasons,
        })
        seen[int(idp)] = seen.get(int(idp), 0) + 1
    result["rows"] = rows
    result["duplicate_idp"] = sorted(idp for idp, count in seen.items() if count > 1)
    result["motive_counts"] = {str(code): sum(row["motive_code"] == code for row in rows) for code in sorted(MOTIVE_NAMES)}
    result["malformed_rows"] = malformed
    result["status"] = "available" if malformed == 0 else "available_with_findings"
    return result


def _source_mapping(metadata: Mapping[str, Any]) -> tuple[dict[int, str], dict[str, int]]:
    binding = metadata.get("physical_binding")
    typed = metadata.get("typed_identity_binding", {})
    source_labels = binding.get("initial_state", {}).get("source_labels", {}) if isinstance(binding, Mapping) else {}
    mapping = typed.get("fluid_mkfluid_to_native_mk", {}) if isinstance(typed, Mapping) else {}
    mk_to_source: dict[int, str] = {}
    source_to_mk: dict[str, int] = {}
    for mkfluid, native_mk in mapping.items():
        label = source_labels.get(f"mkfluid:{int(mkfluid)}")
        if label is None:
            raise ScienceAuditError(f"missing source label for mkfluid {mkfluid}")
        mk_to_source[int(native_mk)] = str(label)
        source_to_mk[str(label)] = int(native_mk)
    if len(mk_to_source) < 2:
        raise ScienceAuditError("F4 science audit requires both typed fluid sources")
    return mk_to_source, source_to_mk


def _finite_aperture(binding: Mapping[str, Any]) -> tuple[float, np.ndarray, np.ndarray]:
    geometry = binding["geometry"]
    if binding["mechanism_id"] == "finite_drop_pool":
        low, high = _bounds(geometry["pool"])
        return float(high[0]), low[[1, 2]], high[[1, 2]]
    if binding["mechanism_id"] == "oblique_finite_columns":
        left_low, left_high = _bounds(geometry["left_column"])
        right_low, right_high = _bounds(geometry["right_column"])
        return float((left_high[0] + right_low[0]) / 2.0), np.maximum(left_low[[1, 2]], right_low[[1, 2]]), np.minimum(left_high[[1, 2]], right_high[[1, 2]])
    raise ScienceAuditError(f"unsupported F4 mechanism: {binding['mechanism_id']}")


def _fluid_source_indices(initial_type: np.ndarray, initial_mk: np.ndarray, source_to_mk: Mapping[str, int]) -> dict[str, np.ndarray]:
    return {label: np.flatnonzero((initial_type == 3) & (initial_mk == native_mk)) for label, native_mk in source_to_mk.items()}


def audit_lifecycle(
    *,
    h5_path: Path,
    metadata: Mapping[str, Any],
    runparts: Mapping[str, Any],
    partout: Mapping[str, Any],
    native_accounting: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Check fixed typed identity lifecycle and close the native exclusion ledger."""

    with h5py.File(h5_path, "r") as h5:
        missing_datasets = [name for name in REQUIRED_H5 if name not in h5]
        if missing_datasets:
            raise ScienceAuditError(f"missing HDF5 datasets: {missing_datasets}")
        times = np.asarray(h5["time"][...], dtype=np.float64)
        ids = np.asarray(h5["particle_id"][...], dtype=np.int64)
        zones = np.asarray(h5["particle_zone"][...], dtype=np.int64)
        initial_type = np.asarray(h5["initial_type"][...], dtype=np.int8)
        initial_mk = np.asarray(h5["initial_mk"][...], dtype=np.int16)
        initial_mass = np.asarray(h5["initial_mass"][...], dtype=np.float64)
        frames = int(times.size)
        particles = int(ids.size)
        shape_failures: list[str] = []
        for name in REQUIRED_H5:
            if name not in {"time", "particle_id", "particle_zone", "initial_type", "initial_mk", "initial_mass"} and h5[name].shape[:2] != (frames, particles):
                shape_failures.append(f"shape:{name}:{h5[name].shape}")
        keys = [(int(zone), int(idp)) for zone, idp in zip(zones, ids)]
        duplicate_keys = sorted({key for key in keys if keys.count(key) > 1})
        if times.size < 2 or not np.isfinite(times).all() or not np.all(np.diff(times) > 0):
            shape_failures.append("time_not_finite_strictly_increasing")
        if not np.isfinite(initial_mass).all() or np.any(initial_mass <= 0):
            shape_failures.append("initial_mass_not_positive_finite")
        first_missing = np.full(particles, -1, dtype=np.int64)
        last_active = np.full(particles, -1, dtype=np.int64)
        ever_missing = np.zeros(particles, dtype=bool)
        revived = np.zeros(particles, dtype=bool)
        previous_valid = np.zeros(particles, dtype=bool)
        previous_type = np.full(particles, -1, dtype=np.int16)
        previous_mk = np.full(particles, -1, dtype=np.int16)
        type_changed = np.zeros(particles, dtype=bool)
        mk_changed = np.zeros(particles, dtype=bool)
        frame_records: list[dict[str, Any]] = []
        active_nonfinite = 0
        active_nonpositive = 0
        valid_nonbinary = 0
        for frame in range(frames):
            valid = np.asarray(h5["valid"][frame, ...], dtype=bool)
            raw_valid = np.asarray(h5["valid"][frame, ...])
            valid_nonbinary += int(np.sum((raw_valid != 0) & (raw_valid != 1))) if raw_valid.dtype != np.bool_ else 0
            types = np.asarray(h5["type"][frame, ...], dtype=np.int8)
            mks = np.asarray(h5["mk"][frame, ...], dtype=np.int16)
            density = np.asarray(h5["density"][frame, ...], dtype=np.float64)
            mass = np.asarray(h5["mass"][frame, ...], dtype=np.float64)
            active = valid
            active_nonfinite += int(np.sum(active & (~np.isfinite(density) | ~np.isfinite(mass))))
            active_nonpositive += int(np.sum(active & ((density <= 0) | (mass <= 0))))
            became_missing = (~valid) & (first_missing < 0)
            first_missing[became_missing] = frame
            ever_missing |= ~valid
            revived |= (~previous_valid) & valid & ever_missing & (frame > 0)
            last_active[valid] = frame
            comparable = valid & previous_valid
            type_changed |= comparable & (types != previous_type)
            mk_changed |= comparable & (mks != previous_mk)
            by_type = {str(kind): int(np.sum(valid & (initial_type == kind))) for kind in (0, 1, 2, 3)}
            by_mk = {str(int(mk)): int(np.sum(~valid & (initial_mk == mk))) for mk in sorted(set(initial_mk.tolist()))}
            frame_records.append({
                "frame": frame,
                "time_s": float(times[frame]),
                "active_particles": int(np.sum(valid)),
                "missing_particles": int(np.sum(~valid)),
                "missing_by_initial_type": {str(kind): int(np.sum((~valid) & (initial_type == kind))) for kind in (0, 1, 2, 3)},
                "missing_by_initial_mk": by_mk,
                "active_by_initial_type": by_type,
            })
            previous_valid = valid
            previous_type = types
            previous_mk = mks
        mk_to_source, source_to_mk = _source_mapping(metadata)
        fluid_indices = np.flatnonzero(initial_type == 3)
        fluid_missing = [index for index in fluid_indices if first_missing[index] >= 0]
        terminal_missing = [index for index in fluid_missing if last_active[index] < frames - 1]
        missing_records = []
        for index in terminal_missing:
            missing_records.append({
                "zone": int(zones[index]),
                "idp": int(ids[index]),
                "initial_mk": int(initial_mk[index]),
                "source": mk_to_source.get(int(initial_mk[index]), "unknown"),
                "first_missing_frame": int(first_missing[index]),
                "first_missing_time_s": float(times[first_missing[index]]),
                "last_active_frame": int(last_active[index]),
                "last_active_time_s": float(times[last_active[index]]) if last_active[index] >= 0 else None,
                "unknown_native_mass_kg": float(initial_mass[index]),
                "state": "numerical_unknown",
                "physical_exit_inferred": False,
            })
        missing_by_source = {
            label: [row for row in missing_records if row["source"] == label]
            for label in sorted(source_to_mk)
        }
    run_totals = dict(runparts.get("totals", {}))
    part_rows = list(partout.get("rows", []))
    part_by_id = {int(row["idp"]): row for row in part_rows}
    missing_ids = {int(row["idp"]) for row in missing_records}
    part_ids = set(part_by_id)
    account_errors: list[str] = []
    if runparts.get("status") not in {"available", "available_with_findings"}:
        account_errors.append("runparts_unavailable")
    if partout.get("status") not in {"available", "available_with_findings"}:
        account_errors.append("partvtkout_unavailable")
    if int(run_totals.get("NpOut", -1)) != len(missing_records):
        account_errors.append("runparts_npout_vs_h5_terminal_missing")
    if part_ids != missing_ids:
        account_errors.append("partvtkout_typed_id_set_vs_h5_terminal_missing")
    motive_counts = {code: 0 for code in MOTIVE_NAMES}
    for row in missing_records:
        part = part_by_id.get(int(row["idp"]))
        if part is None:
            continue
        code = int(part["motive_code"])
        if code not in motive_counts:
            account_errors.append(f"invalid_native_motive:{code}")
        else:
            motive_counts[code] += 1
        if not _finite_vector(part["position_m"]) or not math.isfinite(float(part["density_kg_m3"])):
            account_errors.append(f"nonfinite_partvtk_state:{row['idp']}")
    expected_reason_totals = {
        "NpOutPos": motive_counts[1],
        "NpOutRho": motive_counts[2],
        "NpOutMov": motive_counts[3],
    }
    for key, value in expected_reason_totals.items():
        if int(run_totals.get(key, -1)) != value:
            account_errors.append(f"runparts_{key}_vs_partvtk_motive")
    if len(part_rows) != int(run_totals.get("NpOut", -1)):
        account_errors.append("partvtk_row_count_vs_runparts_npout")
    if duplicate_keys:
        account_errors.append("duplicate_typed_identity_axis")
    if shape_failures:
        account_errors.extend(shape_failures)
    if valid_nonbinary:
        account_errors.append("valid_not_binary")
    if active_nonfinite or active_nonpositive:
        account_errors.append("active_density_or_mass_invalid")
    if np.any(revived):
        account_errors.append("identity_revived_after_missing")
    if np.any(type_changed):
        account_errors.append("identity_type_changed")
    if np.any(mk_changed):
        account_errors.append("identity_mk_changed")
    if native_accounting is not None:
        facts = native_accounting.get("facts", {})
        native_counts = facts.get("excluded_interval_sums", {})
        for key in ("NpOut", "NpOutPos", "NpOutRho", "NpOutMov"):
            if key in native_counts and int(native_counts[key]) != int(run_totals.get(key, -1)):
                account_errors.append(f"native_accounting_{key}_mismatch")
        if int(facts.get("saved_frames", -1)) != frames:
            account_errors.append("native_accounting_frame_count_mismatch")
    closed_no_loss = (not account_errors and len(missing_records) == 0 and all(int(run_totals.get(key, 0)) == 0 for key in ("NpOut", "NpOutPos", "NpOutRho", "NpOutMov")))
    exclusions_closed = len(account_errors) == 0 and len(missing_records) == int(run_totals.get("NpOut", -1))
    return {
        "schema": "ds02.f4.lifecycle-audit.v2",
        "status": "pass" if (closed_no_loss or exclusions_closed) else "fail",
        "q_i_claim": "typed lifecycle evidence only; no Q-N",
        "frames": frames,
        "particles": particles,
        "time": {
            "finite": bool(np.isfinite(times).all()),
            "strictly_increasing": bool(times.size >= 2 and np.all(np.diff(times) > 0)),
            "start_s": float(times[0]) if frames else None,
            "end_s": float(times[-1]) if frames else None,
        },
        "typed_identity": {
            "key": "(Zone,Idp)",
            "unique": not duplicate_keys,
            "initial_type_counts": {str(kind): int(np.sum(initial_type == kind)) for kind in (0, 1, 2, 3)},
            "initial_mk_counts": {str(int(mk)): int(np.sum(initial_mk == mk)) for mk in sorted(set(initial_mk.tolist()))},
            "fluid_mk_to_source": {str(mk): label for mk, label in mk_to_source.items()},
        },
        "valid_mask": {"binary": valid_nonbinary == 0, "dataset_dtype": str(h5py.h5t.NATIVE_HBOOL) if False else "bool_checked"},
        "active_finite_positive": {"nonfinite_count": active_nonfinite, "nonpositive_count": active_nonpositive},
        "lifecycle": {
            "initial_fluid_typed_count": len(fluid_indices),
            "terminal_missing_fluid_typed_count": len(terminal_missing),
            "introduced_after_initial_count": 0,
            "revived_identity_count": int(np.sum(revived)),
            "type_changed_identity_count": int(np.sum(type_changed)),
            "mk_changed_identity_count": int(np.sum(mk_changed)),
            "missing_by_source": missing_by_source,
            "missing_typed_identity_records": missing_records,
            "missing_state_semantics": "missing valid rows are numerical unknown; no physical exit, spill, or redistribution is inferred",
            "frame_records": frame_records,
        },
        "native_exclusion_ledger": {
            "runparts": runparts,
            "partvtkout": partout,
            "motive_code_semantics": MOTIVE_NAMES,
            "motive_counts": {str(code): int(count) for code, count in motive_counts.items()},
            "native_accounting": native_accounting,
            "closure": "closed_no_loss" if closed_no_loss else ("closed_numerical_unknown" if exclusions_closed else "open_or_mismatch"),
            "physical_exit_classification": "not_inferred",
        },
        "errors": sorted(set(account_errors)),
        "source_h5": {"path": str(h5_path), "sha256": sha256_file(h5_path)},
    }


def _support_detector(
    points_a: np.ndarray,
    points_b: np.ndarray,
    masses_a: np.ndarray,
    masses_b: np.ndarray,
    *,
    radius_m: float = 0.02,
    minimum_pairs: int = 3,
    minimum_mass_fraction: float = 0.01,
    source_mass_scale_kg: float | None = None,
) -> dict[str, Any]:
    """Detect interaction from two active source clouds, never source boxes."""

    if cKDTree is None:
        raise ScienceAuditError("scipy.spatial.cKDTree is required for source-support audit")
    points_a = np.asarray(points_a, dtype=np.float64)
    points_b = np.asarray(points_b, dtype=np.float64)
    masses_a = np.asarray(masses_a, dtype=np.float64)
    masses_b = np.asarray(masses_b, dtype=np.float64)
    if points_a.size == 0 or points_b.size == 0:
        return {"contact": False, "support_pairs": 0, "support_mass_kg": 0.0, "min_distance_m": None}
    tree = cKDTree(points_b)
    distances, neighbours = tree.query(points_a, k=1)
    close = np.isfinite(distances) & (distances <= radius_m)
    pair_count = int(np.sum(close))
    if pair_count:
        unique_b = np.unique(np.asarray(neighbours[close], dtype=np.int64))
        mass_a = float(np.sum(masses_a[close]))
        mass_b = float(np.sum(masses_b[unique_b]))
        support_mass = min(mass_a, mass_b)
        minimum_mass = float(source_mass_scale_kg if source_mass_scale_kg is not None else min(np.sum(masses_a), np.sum(masses_b)))
    else:
        support_mass = 0.0
        minimum_mass = float(source_mass_scale_kg if source_mass_scale_kg is not None else min(np.sum(masses_a), np.sum(masses_b)))
    threshold = minimum_mass * minimum_mass_fraction
    return {
        "contact": bool(pair_count >= minimum_pairs and support_mass >= threshold),
        "support_pairs": pair_count,
        "support_mass_kg": support_mass,
        "support_mass_threshold_kg": threshold,
        "min_distance_m": float(np.min(distances)) if distances.size else None,
    }


def _calibration() -> dict[str, Any]:
    """Run deterministic translation/rotation/sampling detector calibration."""

    grid = np.asarray([[x, y, z] for x in (0.0, 0.02, 0.04) for y in (0.0, 0.02) for z in (0.0, 0.02)], dtype=np.float64)
    masses = np.full(grid.shape[0], 1.0, dtype=np.float64)
    translations = [0.05, 0.03, 0.019, 0.0]
    translation_records = []
    for offset in translations:
        # The base cloud spans x=0..0.04.  The extra 0.04 keeps ``offset``
        # equal to the physical gap rather than the translation of an already
        # overlapping cloud.
        shifted = grid + np.array([0.04 + offset, 0.0, 0.0])
        result = _support_detector(grid, shifted, masses, masses, source_mass_scale_kg=float(masses.sum()))
        translation_records.append({"offset_m": offset, **result})
    angle = math.pi / 2.0
    rotation = np.asarray([[math.cos(angle), -math.sin(angle), 0.0], [math.sin(angle), math.cos(angle), 0.0], [0.0, 0.0, 1.0]])
    rotated = (grid - grid.mean(axis=0)) @ rotation.T + grid.mean(axis=0) + np.array([0.015, 0.0, 0.0])
    rotation_result = _support_detector(grid, rotated, masses, masses, source_mass_scale_kg=float(masses.sum()))
    sampled = grid[::2]
    sampling_result = _support_detector(grid, sampled + np.array([0.015, 0.0, 0.0]), masses, masses[::2], source_mass_scale_kg=float(masses.sum()))
    first_detected = next((row["offset_m"] for row in translation_records if row["contact"]), None)
    return {
        "schema": "ds02.f4.source-support-calibration.v1",
        "registered_radius_m": 0.02,
        "minimum_support_pairs": 3,
        "minimum_support_mass_fraction": 0.01,
        "translation": translation_records,
        "rotation_fixture": rotation_result,
        "sampling_fixture": sampling_result,
        "translation_detected_at_or_below_m": first_detected,
        "interpretation": "calibration bounds sampling/translation sensitivity; it is not a physical F4 result",
    }


def _source_geometry(metadata: Mapping[str, Any]) -> dict[str, Any]:
    binding = metadata["physical_binding"]
    geometry = binding["geometry"]
    sources = {name: region for name, region in geometry.items() if isinstance(region, Mapping) and "mkfluid" in region}
    return {"binding": binding, "sources": sources}


def _curve_fieldnames(source_labels: Sequence[str]) -> list[str]:
    fields = [
        "frame", "time_s", "active_mass_kg", "unknown_fluid_mass_kg",
        "momentum_x_kg_m_s", "momentum_y_kg_m_s", "momentum_z_kg_m_s", "kinetic_energy_j",
    ]
    for label in source_labels:
        fields.extend([
            f"{label}_mass_kg", f"{label}_com_x_m", f"{label}_com_y_m", f"{label}_com_z_m",
            f"{label}_momentum_x_kg_m_s", f"{label}_momentum_y_kg_m_s", f"{label}_momentum_z_kg_m_s",
            f"{label}_kinetic_energy_j", f"{label}_spread_x_m", f"{label}_spread_y_m", f"{label}_spread_z_m", f"{label}_spread_extent_m",
            f"{label}_finite_aperture_mass_kg", f"{label}_finite_aperture_particles",
        ])
    fields.extend(["source_support_contact", "source_support_pairs", "source_support_mass_kg", "source_support_min_distance_m"])
    return fields


def compute_curve_and_events(
    *,
    h5_path: Path,
    metadata: Mapping[str, Any],
    operators: Mapping[str, Any],
    output_csv: Path,
) -> dict[str, Any]:
    """Stream one HDF5 and write complete actual-time macro/event curves."""

    binding = metadata["physical_binding"]
    mk_to_source, source_to_mk = _source_mapping(metadata)
    source_labels = sorted(source_to_mk)
    source_indices_static: dict[str, np.ndarray]
    plane_x, aperture_low, aperture_high = _finite_aperture(binding)
    radius_m = float(operators["physical_support"]["support_radius_m"])
    minimum_pairs = int(operators["physical_support"]["minimum_cross_support_pairs"])
    minimum_mass_fraction = float(operators["physical_support"]["minimum_support_mass_fraction_of_smaller_source"])
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    support_flags: list[bool] = []
    support_rows: list[dict[str, Any]] = []
    source_event_data = {
        label: {
            "first_passage": None,
            "positive_crossings": 0,
            "negative_crossings": 0,
            "positive_crossing_mass_kg": 0.0,
            "negative_crossing_mass_kg": 0.0,
            "repeat_crossings": 0,
            "residence_mass_time_kg_s": 0.0,
            "residence_particle_time_s": None,
            "known_residence_particles": 0,
        }
        for label in source_labels
    }
    with h5py.File(h5_path, "r") as h5:
        times = np.asarray(h5["time"][...], dtype=np.float64)
        frames = int(times.size)
        particles = int(h5["particle_id"].shape[0])
        initial_type = np.asarray(h5["initial_type"][...], dtype=np.int8)
        initial_mk = np.asarray(h5["initial_mk"][...], dtype=np.int16)
        initial_mass = np.asarray(h5["initial_mass"][...], dtype=np.float64)
        source_indices_static = _fluid_source_indices(initial_type, initial_mk, source_to_mk)
        source_initial_mass = {label: float(np.sum(initial_mass[index])) for label, index in source_indices_static.items()}
        previous_x = np.full(particles, np.nan, dtype=np.float64)
        previous_known = np.zeros(particles, dtype=bool)
        previous_aperture = np.zeros(particles, dtype=bool)
        previous_plane_mass = {label: 0.0 for label in source_labels}
        residence_particle_time = {label: np.zeros(particles, dtype=np.float64) for label in source_labels}
        fieldnames = _curve_fieldnames(source_labels)
        with output_csv.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            for frame in range(frames):
                valid = np.asarray(h5["valid"][frame, ...], dtype=bool)
                types = np.asarray(h5["type"][frame, ...], dtype=np.int8)
                positions = np.asarray(h5["position"][frame, ...], dtype=np.float64)
                velocities = np.asarray(h5["velocity"][frame, ...], dtype=np.float64)
                masses = np.asarray(h5["mass"][frame, ...], dtype=np.float64)
                active = valid & (types == 3) & (initial_type == 3)
                # Keep a snapshot because the per-source loop advances the
                # persistent arrays before the residence integral is formed.
                prior_known = previous_known.copy()
                prior_aperture = previous_aperture.copy()
                row: dict[str, Any] = {
                    "frame": frame,
                    "time_s": float(times[frame]),
                    "active_mass_kg": float(np.sum(masses[active])),
                    "unknown_fluid_mass_kg": float(np.sum(initial_mass[(initial_type == 3) & ~valid])),
                    "momentum_x_kg_m_s": float(np.sum(masses[active] * velocities[active, 0])),
                    "momentum_y_kg_m_s": float(np.sum(masses[active] * velocities[active, 1])),
                    "momentum_z_kg_m_s": float(np.sum(masses[active] * velocities[active, 2])),
                    "kinetic_energy_j": float(0.5 * np.sum(masses[active] * np.sum(velocities[active] ** 2, axis=1))),
                }
                current_plane_mass = {label: 0.0 for label in source_labels}
                current_aperture = np.zeros(particles, dtype=bool)
                support = {"contact": False, "support_pairs": 0, "support_mass_kg": 0.0, "min_distance_m": None}
                for label in source_labels:
                    index = source_indices_static[label]
                    selected = active[index]
                    selected_index = index[selected]
                    p = positions[selected_index]
                    v = velocities[selected_index]
                    m = masses[selected_index]
                    aperture = np.zeros(selected_index.size, dtype=bool)
                    if selected_index.size:
                        aperture = np.all((p[:, [1, 2]] >= aperture_low) & (p[:, [1, 2]] <= aperture_high), axis=1)
                        current_aperture[selected_index] = aperture & (p[:, 0] >= plane_x)
                        current_plane_mass[label] = float(np.sum(m[current_aperture[selected_index]]))
                    mass = float(np.sum(m))
                    if mass > 0:
                        com = np.sum(p * m[:, None], axis=0) / mass
                        min_pos = np.min(p, axis=0)
                        max_pos = np.max(p, axis=0)
                        spread = max_pos - min_pos
                        momentum = np.sum(v * m[:, None], axis=0)
                        energy = float(0.5 * np.sum(m * np.sum(v * v, axis=1)))
                    else:
                        com = np.full(3, np.nan)
                        spread = np.full(3, np.nan)
                        momentum = np.full(3, np.nan)
                        energy = math.nan
                    row.update({
                        f"{label}_mass_kg": mass,
                        f"{label}_com_x_m": float(com[0]), f"{label}_com_y_m": float(com[1]), f"{label}_com_z_m": float(com[2]),
                        f"{label}_momentum_x_kg_m_s": float(momentum[0]), f"{label}_momentum_y_kg_m_s": float(momentum[1]), f"{label}_momentum_z_kg_m_s": float(momentum[2]),
                        f"{label}_kinetic_energy_j": energy,
                        f"{label}_spread_x_m": float(spread[0]), f"{label}_spread_y_m": float(spread[1]), f"{label}_spread_z_m": float(spread[2]), f"{label}_spread_extent_m": float(np.max(spread)) if np.isfinite(spread).all() else math.nan,
                        f"{label}_finite_aperture_mass_kg": current_plane_mass[label],
                        f"{label}_finite_aperture_particles": int(np.sum(current_aperture[index])),
                    })
                    previous_source_x = previous_x[index]
                    previous_source_known = previous_known[index]
                    current_x = np.full(index.size, np.nan, dtype=np.float64)
                    current_x[selected] = p[:, 0]
                    crossed = previous_source_known & selected & np.isfinite(previous_source_x) & np.isfinite(current_x) & ((previous_source_x < plane_x) != (current_x < plane_x))
                    if np.any(crossed):
                        prev_ap = previous_aperture[index]
                        now_ap = current_aperture[index]
                        crossing = crossed & prev_ap & now_ap
                        positive = crossing & (previous_source_x < plane_x) & (current_x >= plane_x)
                        negative = crossing & ~positive
                        data = source_event_data[label]
                        data["positive_crossings"] += int(np.sum(positive))
                        data["negative_crossings"] += int(np.sum(negative))
                        data["positive_crossing_mass_kg"] += float(np.sum(initial_mass[index[positive]]))
                        data["negative_crossing_mass_kg"] += float(np.sum(initial_mass[index[negative]]))
                        data["repeat_crossings"] += int(np.sum(crossing))
                        if data["first_passage"] is None and np.any(positive):
                            particle_indices = np.flatnonzero(positive)
                            candidate = int(particle_indices[0])
                            x0 = float(previous_source_x[candidate])
                            x1 = float(current_x[candidate])
                            frac = (plane_x - x0) / (x1 - x0) if x1 != x0 else 0.5
                            data["first_passage"] = {
                                "status": "observed",
                                "bracket_s": [float(times[frame - 1]), float(times[frame])] if frame else [float(times[frame]), float(times[frame])],
                                "linear_time_s": float(times[frame - 1] + frac * (times[frame] - times[frame - 1])) if frame else float(times[frame]),
                                "frame": frame,
                            }
                    previous_x[index] = current_x
                    previous_known[index] = selected
                    previous_aperture[index] = current_aperture[index]
                if len(source_labels) == 2:
                    first_label, second_label = source_labels
                    ia = source_indices_static[first_label][active[source_indices_static[first_label]]]
                    ib = source_indices_static[second_label][active[source_indices_static[second_label]]]
                    support = _support_detector(
                        positions[ia], positions[ib], masses[ia], masses[ib], radius_m=radius_m,
                        minimum_pairs=minimum_pairs, minimum_mass_fraction=minimum_mass_fraction,
                        source_mass_scale_kg=min(source_initial_mass[first_label], source_initial_mass[second_label]),
                    )
                support_flags.append(bool(support["contact"]))
                support_rows.append({
                    "frame": frame, "time_s": float(times[frame]), **support,
                })
                row["source_support_contact"] = int(bool(support["contact"]))
                row["source_support_pairs"] = int(support["support_pairs"])
                row["source_support_mass_kg"] = float(support["support_mass_kg"])
                row["source_support_min_distance_m"] = support["min_distance_m"]
                if frame > 0:
                    dt = float(times[frame] - times[frame - 1])
                    for label in source_labels:
                        source_event_data[label]["residence_mass_time_kg_s"] += 0.5 * dt * (previous_plane_mass[label] + current_plane_mass[label])
                    both_known = prior_known & np.isfinite(previous_x) & np.isfinite(positions[:, 0]) & valid
                    for label in source_labels:
                        index = source_indices_static[label]
                        known = both_known[index]
                        inside_prev = prior_aperture[index]
                        inside_now = current_aperture[index]
                        residence_particle_time[label][index[known]] += dt * 0.5 * (inside_prev[known].astype(np.float64) + inside_now[known].astype(np.float64))
                previous_plane_mass = current_plane_mass
                writer.writerow(row)
                rows.append(row)
    contact_first = _event_from_flags(np.asarray([row["time_s"] for row in support_rows], dtype=np.float64), support_flags)
    recontact = _recontact_from_flags(np.asarray([row["time_s"] for row in support_rows], dtype=np.float64), support_flags, contact_first)
    for label in source_labels:
        values = residence_particle_time[label]
        observed = values[values > 0]
        source_event_data[label]["known_residence_particles"] = int(observed.size)
        source_event_data[label]["residence_particle_time_s"] = float(np.mean(observed)) if observed.size else None
    labels = {
        "schema": "ds02.f4.typed-science-labels.v2",
        "h5": {"path": str(h5_path), "sha256": sha256_file(h5_path)},
        "physical_binding_sha256": metadata.get("physical_binding_sha256", canonical_hash(binding)),
        "control_reference_sha256": None,
        "identity_key": "(Zone,Idp)",
        "source_mk_to_label": {str(mk): label for mk, label in mk_to_source.items()},
        "finite_aperture": {"plane_x_m": plane_x, "y_z_low_m": aperture_low.tolist(), "y_z_high_m": aperture_high.tolist()},
        "curves": {"path": str(output_csv), "sha256": sha256_file(output_csv), "rows": len(rows)},
        "contact": {"operator": "typed active source-support; initial region entry is excluded", "timeseries": support_rows, "first_contact": contact_first, "recontact": recontact},
        "transport": source_event_data,
        "status": "actual typed HDF5 sidecar; no qualification claim",
    }
    return {"labels": labels, "rows": rows, "support_rows": support_rows, "source_event_data": source_event_data, "contact_first": contact_first, "recontact": recontact, "source_labels": source_labels, "physical_binding_sha256": metadata.get("physical_binding_sha256", canonical_hash(binding))}


def _scale_contract(metadata: Mapping[str, Any], save_plan: Mapping[str, Any] | None) -> dict[str, float | None]:
    mechanism = str(metadata["mechanism_id"])
    entry = ((save_plan or {}).get("scale_contract", {}) if isinstance(save_plan, Mapping) else {}).get(mechanism, {})
    L = _number(entry.get("L_m")) if isinstance(entry, Mapping) else None
    if L is None:
        L = 0.16
    binding = metadata["physical_binding"]
    parameters = binding.get("parameters", {})
    if mechanism == "finite_drop_pool":
        T = _number(entry.get("T_s")) if isinstance(entry, Mapping) else None
        if T is None:
            speed = abs(float(parameters.get("speed_m_per_s", 0.5)))
            T = L / max(speed, 1.0e-12)
    else:
        vy = float(parameters.get("transverse_speed_m_per_s", parameters.get("vy_m_per_s", 0.25)))
        U = math.sqrt(1.0 + vy * vy)
        T = L / U
    T = float(T)
    return {"L_m": float(L), "T_s": T, "U_m_per_s": float(L / T), "mass_scale_kg": None}


def _curve_arrays(report: Mapping[str, Any]) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    rows = report["curve_rows"]
    times = np.asarray([float(row["time_s"]) for row in rows], dtype=np.float64)
    fields = sorted({key for row in rows for key in row if key not in {"frame", "time_s"}})
    return times, {field: np.asarray([_number(row.get(field), math.nan) for row in rows], dtype=np.float64) for field in fields}


def compare_artifacts(
    *,
    artifacts: Sequence[Mapping[str, Any]],
    output_dir: Path,
    save_plan: Mapping[str, Any] | None,
    operators: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare actual curves by physical time, with complete pair curves."""

    by_case: dict[str, list[Mapping[str, Any]]] = {}
    for artifact in artifacts:
        by_case.setdefault(str(artifact["case_id"]), []).append(artifact)
    comparisons: list[dict[str, Any]] = []
    for case_id, members in sorted(by_case.items()):
        reference = next((item for item in members if item["resolution"] == "fine" and item["time_variant"] == "native"), None)
        if reference is None:
            continue
        ref_times, ref_curves = _curve_arrays(reference)
        binding = reference["metadata"]["physical_binding"]
        scale = _scale_contract(reference["metadata"], save_plan)
        initial_mass_by_source = {
            label: float(value)
            for label, value in reference["metadata"].get("initialization_evidence", {}).get("native_initial_mass_by_source_kg", {}).items()
        }
        if not initial_mass_by_source:
            initial_mass_by_source = {label: float(reference["initial_source_mass_kg"].get(label, 1.0)) for label in reference["source_labels"]}
        U = float(scale["U_m_per_s"] or 1.0)
        L = float(scale["L_m"] or 1.0)
        scale_mass = float(sum(initial_mass_by_source.values()))
        metric_scales: dict[str, float] = {"active_mass_kg": max(scale_mass, 1.0e-12), "momentum_x_kg_m_s": max(scale_mass * U, 1.0e-12), "momentum_y_kg_m_s": max(scale_mass * U, 1.0e-12), "momentum_z_kg_m_s": max(scale_mass * U, 1.0e-12), "kinetic_energy_j": max(scale_mass * U * U, 1.0e-12)}
        for label in reference["source_labels"]:
            mscale = max(initial_mass_by_source.get(label, 1.0), 1.0e-12)
            metric_scales.update({
                f"{label}_mass_kg": mscale,
                f"{label}_com_x_m": L, f"{label}_com_y_m": L, f"{label}_com_z_m": L,
                f"{label}_momentum_x_kg_m_s": mscale * U, f"{label}_momentum_y_kg_m_s": mscale * U, f"{label}_momentum_z_kg_m_s": mscale * U,
                f"{label}_kinetic_energy_j": mscale * U * U,
                f"{label}_spread_x_m": L, f"{label}_spread_y_m": L, f"{label}_spread_z_m": L, f"{label}_spread_extent_m": L,
            })
        metrics = [key for key in metric_scales if key in ref_curves]
        for candidate in sorted(members, key=lambda item: (item["resolution"], item["time_variant"])):
            if candidate is reference:
                continue
            cand_times, cand_curves = _curve_arrays(candidate)
            start = max(float(ref_times[0]), float(cand_times[0]))
            end = min(float(ref_times[-1]), float(cand_times[-1]))
            mask = (cand_times >= start) & (cand_times <= end)
            if not np.any(mask):
                continue
            aligned_time = cand_times[mask]
            curve_path = output_dir / "comparisons" / f"{case_id}-{candidate['resolution']}-{candidate['time_variant']}-vs-fine-native.csv"
            curve_path.parent.mkdir(parents=True, exist_ok=True)
            metric_max: dict[str, float] = {}
            metric_p95: dict[str, float] = {}
            with curve_path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=["time_s", "metric", "reference_value", "candidate_value", "absolute_error", "normalized_error"])
                writer.writeheader()
                for metric in metrics:
                    reference_values = np.interp(aligned_time, ref_times, ref_curves[metric])
                    candidate_values = cand_curves.get(metric, np.full(cand_times.size, math.nan))[mask]
                    errors = np.abs(candidate_values - reference_values) / metric_scales[metric]
                    finite = np.isfinite(errors)
                    if np.any(finite):
                        metric_max[metric] = float(np.max(errors[finite]))
                        metric_p95[metric] = float(np.percentile(errors[finite], 95))
                    else:
                        metric_max[metric] = math.nan
                        metric_p95[metric] = math.nan
                    for t, ref_value, cand_value, error in zip(aligned_time, reference_values, candidate_values, errors):
                        writer.writerow({"time_s": float(t), "metric": metric, "reference_value": float(ref_value), "candidate_value": float(cand_value), "absolute_error": float(abs(cand_value - ref_value)), "normalized_error": float(error)})
            ref_contact = reference["science"]["contact_first"]
            cand_contact = candidate["science"]["contact_first"]
            event_budget = EVENT_ERROR_BUDGET * float(scale["T_s"] or 0.0)
            temporal_budget = TEMPORAL_ITEM_ALLOCATION * event_budget
            temporal_pair = candidate["time_variant"] in {"half_dt", "half_save"}
            timing: dict[str, Any]
            if ref_contact.get("status") == "observed" and cand_contact.get("status") == "observed":
                ref_t = float(ref_contact["time_s"])
                cand_t = float(cand_contact["time_s"])
                ref_bracket = ref_contact.get("bracket_s") or [ref_t, ref_t]
                cand_bracket = cand_contact.get("bracket_s") or [cand_t, cand_t]
                uncertainty = 0.5 * ((ref_bracket[1] - ref_bracket[0]) + (cand_bracket[1] - cand_bracket[0]))
                offset = cand_t - ref_t
                threshold = temporal_budget if temporal_pair else event_budget
                timing = {"status": "within_budget" if abs(offset) <= threshold else "fail_over_budget", "reference_time_s": ref_t, "candidate_time_s": cand_t, "offset_s": offset, "uncertainty_half_width_s": uncertainty, "reference_bracket_s": ref_bracket, "candidate_bracket_s": cand_bracket, "budget_s": threshold, "budget_kind": "temporal_item_20pct_of_event_budget" if temporal_pair else "event_2pct_T"}
            else:
                timing = {"status": "right_censored_or_unresolved", "reference": ref_contact, "candidate": cand_contact, "budget_s": temporal_budget if temporal_pair else event_budget, "budget_kind": "temporal_item_20pct_of_event_budget" if temporal_pair else "event_2pct_T"}
            observed_max = max((value for value in metric_max.values() if math.isfinite(value)), default=math.nan)
            comparison_status = "within_macro_budget" if math.isfinite(observed_max) and observed_max <= float(operators.get("comparison", {}).get("macro_error_budget_fraction", MACRO_ERROR_BUDGET)) else "fail_over_macro_budget"
            comparisons.append({
                "case_id": case_id,
                "reference_artifact": reference["artifact_id"],
                "candidate_artifact": candidate["artifact_id"],
                "physical_binding_sha256": reference["physical_binding_sha256"],
                "candidate_physical_binding_sha256": candidate["physical_binding_sha256"],
                "control_reference_sha256": reference["h5_attributes"].get("control_reference_sha256"),
                "candidate_control_reference_sha256": candidate["h5_attributes"].get("control_reference_sha256"),
                "candidate_control_sha256": candidate["h5_attributes"].get("control_sha256"),
                "actual_time_overlap_s": [start, end],
                "time_alignment": "actual time interpolation",
                "scale_contract": scale,
                "macro_error_budget_fraction": float(operators.get("comparison", {}).get("macro_error_budget_fraction", MACRO_ERROR_BUDGET)),
                "metric_max_normalized_error": metric_max,
                "metric_p95_normalized_error": metric_p95,
                "max_normalized_error": observed_max,
                "macro_status": comparison_status,
                "event_timing": timing,
                "curve_csv": {"path": str(curve_path), "sha256": sha256_file(curve_path)},
                "qualification_claim": "none",
            })
    return {
        "schema": "ds02.f4.comparison-report.v2",
        "comparison_count": len(comparisons),
        "comparisons": comparisons,
        "status": "observed_reference_comparisons; no Q-N",
    }


def _render_frame(h5: h5py.File, frame: int, initial_type: np.ndarray, initial_mk: np.ndarray, source_labels: Mapping[int, str], *, max_points: int = 5000):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from PIL import Image
    valid = np.asarray(h5["valid"][frame, ...], dtype=bool)
    types = np.asarray(h5["type"][frame, ...], dtype=np.int8)
    positions = np.asarray(h5["position"][frame, ...], dtype=np.float64)
    fluid = valid & (types == 3) & (initial_type == 3)
    boundary = valid & (initial_type == 0)
    figure, axis = plt.subplots(figsize=(7.0, 4.5), dpi=110)
    if np.any(boundary):
        boundary_index = np.flatnonzero(boundary)
        if boundary_index.size > max_points:
            boundary_index = boundary_index[np.linspace(0, boundary_index.size - 1, max_points, dtype=int)]
        axis.scatter(positions[boundary_index, 0], positions[boundary_index, 2], s=2, c="#bdbdbd", alpha=0.22, label="fixed")
    colors = {0: "#1f77b4", 1: "#d62728", 2: "#2ca02c", 3: "#9467bd"}
    for mk in sorted(set(initial_mk[fluid].tolist())):
        index = np.flatnonzero(fluid & (initial_mk == mk))
        if index.size > max_points:
            index = index[np.linspace(0, index.size - 1, max_points, dtype=int)]
        axis.scatter(positions[index, 0], positions[index, 2], s=5, c=colors.get(int(mk), "#ff7f0e"), alpha=0.7, label=source_labels.get(int(mk), f"mk={mk}"))
    axis.set_xlabel("x [m]")
    axis.set_ylabel("z [m]")
    axis.set_title(f"actual frame {frame}, t={float(h5['time'][frame]):.6f} s")
    axis.legend(loc="best", fontsize=7)
    axis.grid(alpha=0.18)
    figure.tight_layout()
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png")
    plt.close(figure)
    buffer.seek(0)
    return Image.open(buffer).convert("P", palette=Image.Palette.ADAPTIVE)


def render_previews(*, h5_path: Path, output_dir: Path, artifact_id: str, metadata: Mapping[str, Any], gif: bool) -> dict[str, Any]:
    preview_dir = output_dir / "previews" / artifact_id
    preview_dir.mkdir(parents=True, exist_ok=True)
    mk_to_source, _ = _source_mapping(metadata)
    source_labels = {native_mk: label for native_mk, label in mk_to_source.items()}
    keyframes: list[dict[str, Any]] = []
    with h5py.File(h5_path, "r") as h5:
        frames = int(h5["time"].shape[0])
        initial_type = np.asarray(h5["initial_type"][...], dtype=np.int8)
        initial_mk = np.asarray(h5["initial_mk"][...], dtype=np.int16)
        for frame in sorted(set((0, frames // 2, frames - 1))):
            image = _render_frame(h5, frame, initial_type, initial_mk, source_labels)
            path = preview_dir / f"keyframe_{frame:05d}.png"
            image.save(path)
            keyframes.append({"frame": frame, "time_s": float(h5["time"][frame]), "path": str(path), "sha256": sha256_file(path), "display_only_downsample": True})
        animation = None
        if gif:
            frame_ids = np.linspace(0, frames - 1, min(18, frames), dtype=int).tolist()
            images = [_render_frame(h5, frame, initial_type, initial_mk, source_labels) for frame in frame_ids]
            gif_path = preview_dir / "actual_trajectory.gif"
            if images:
                images[0].save(gif_path, save_all=True, append_images=images[1:], duration=100, loop=0, optimize=False)
                animation = {"path": str(gif_path), "sha256": sha256_file(gif_path), "frames": frame_ids, "actual_time_s": [float(h5["time"][frame]) for frame in frame_ids], "display_only_downsample": True}
    return {"schema": "ds02.f4.actual-preview.v2", "h5": {"path": str(h5_path), "sha256": sha256_file(h5_path)}, "keyframes": keyframes, "animation": animation, "full_h5_retained": True}


def _artifact_native_accounting(native_rows: Sequence[Mapping[str, Any]], solver_root: Path) -> Mapping[str, Any] | None:
    attempt_id = solver_root.parent.name
    for row in native_rows:
        if str(row.get("attempt_id")) == attempt_id:
            return row
    return None


def _solver_root_from_metadata(metadata: Mapping[str, Any]) -> Path:
    source_binding = metadata.get("source_binding", {})
    solver_log = source_binding.get("solver_log", {}) if isinstance(source_binding, Mapping) else {}
    solver_log_path = solver_log.get("path") if isinstance(solver_log, Mapping) else None
    if not solver_log_path:
        raise ScienceAuditError("F4 metadata has no bound native solver log")
    path = Path(str(solver_log_path)).resolve()
    if path.name != "Run.out" or not path.is_file():
        raise ScienceAuditError(f"bound native solver log is missing or not Run.out: {path}")
    return path.parent


def audit_manifest(
    *,
    manifest_path: Path,
    operators_path: Path,
    native_accounting_path: Path,
    scale_plan_path: Path | None,
    output_dir: Path,
    partvtkout: Path,
    render: bool = True,
) -> dict[str, Any]:
    """Run all actual F4 reference audits into a new unique attempt directory."""

    if output_dir.exists() and any(output_dir.iterdir()):
        raise ScienceAuditError(f"refusing to overwrite non-empty output attempt: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    operators = _load_object(operators_path)
    if operators.get("schema") != OPERATORS_SCHEMA:
        raise ScienceAuditError(f"unexpected science operator schema: {operators.get('schema')}")
    manifest = _load_json(manifest_path)
    if not isinstance(manifest, list) or len(manifest) != 10:
        raise ScienceAuditError("F4 science manifest must contain the ten consumed conversion artifacts")
    native_rows = _load_json(native_accounting_path)
    if not isinstance(native_rows, list):
        raise ScienceAuditError("native accounting must be a list")
    save_plan = _load_object(scale_plan_path) if scale_plan_path is not None else None
    started = time.monotonic()
    before = _resource_snapshot()
    calibration = _calibration()
    artifacts: list[dict[str, Any]] = []
    for item in manifest:
        artifact_id = str(item["artifact_id"])
        h5_path = Path(item["h5"])
        metadata_path = Path(item["metadata"])
        conversion_report_path = Path(item.get("conversion_report", "")) if item.get("conversion_report") else None
        metadata = _load_object(metadata_path)
        binding = metadata.get("physical_binding")
        if not isinstance(binding, Mapping):
            raise ScienceAuditError(f"metadata lacks physical binding: {metadata_path}")
        _, source_to_mk = _source_mapping(metadata)
        solver_root = _solver_root_from_metadata(metadata)
        runparts_path = solver_root / "RunPARTs.csv"
        partout_data = solver_root / "data"
        artifact_output = output_dir / "artifacts" / artifact_id
        artifact_output.mkdir(parents=True, exist_ok=True)
        native_accounting = _artifact_native_accounting(native_rows, solver_root)
        partvtk_run = run_partvtkout(binary=partvtkout, data_dir=partout_data, output_dir=artifact_output / "native-partvtkout")
        runparts = _read_runparts(runparts_path)
        partout = _parse_partvtk_csv(Path(partvtk_run["csv"]), runparts) if partvtk_run["status"] == "available" else {"status": "failed", "rows": [], "motive_counts": {}}
        lifecycle = audit_lifecycle(h5_path=h5_path, metadata=metadata, runparts=runparts, partout=partout, native_accounting=native_accounting)
        curve_path = artifact_output / "typed-science-timeseries.csv"
        science = compute_curve_and_events(h5_path=h5_path, metadata=metadata, operators=operators, output_csv=curve_path)
        science["labels_path"] = str(artifact_output / "typed-science-labels.json")
        Path(science["labels_path"]).write_text(json.dumps(science["labels"], indent=2, sort_keys=True, default=_json_default) + "\n", encoding="utf-8")
        preview = render_previews(h5_path=h5_path, output_dir=artifact_output, artifact_id=artifact_id, metadata=metadata, gif=render and metadata.get("resolution") == "fine" and metadata.get("time_variant") == "native") if render else {"status": "not_requested"}
        with h5py.File(h5_path, "r") as h5:
            h5_attrs = {str(key): _json_value(value) for key, value in h5.attrs.items()}
            curve_rows = []
            with curve_path.open(newline="", encoding="utf-8") as stream:
                curve_rows = [dict(row) for row in csv.DictReader(stream)]
        artifact_report = {
            "artifact_id": artifact_id,
            "case_id": item["case_id"],
            "resolution": metadata.get("resolution"),
            "time_variant": metadata.get("time_variant"),
            "mechanism_id": metadata.get("mechanism_id"),
            "physical_binding_sha256": metadata.get("physical_binding_sha256", canonical_hash(binding)),
            "physical_condition_sha256": h5_attrs.get("physical_condition_sha256"),
            "h5_attributes": h5_attrs,
            "source_labels": sorted(source_to_mk),
            "initial_source_mass_kg": {
                label: float(value)
                for label, value in metadata.get("initialization_evidence", {}).get("native_initial_mass_by_source_kg", {}).items()
            },
            "metadata": metadata,
            "h5": {"path": str(h5_path), "sha256": sha256_file(h5_path)},
            "metadata_file": {"path": str(metadata_path), "sha256": sha256_file(metadata_path)},
            "conversion_report": {"path": str(conversion_report_path), "sha256": sha256_file(conversion_report_path)} if conversion_report_path and conversion_report_path.is_file() else None,
            "native": {"solver_root": str(solver_root), "runparts": runparts, "partvtkout_run": partvtk_run, "partvtkout": partout, "accounting": native_accounting},
            "lifecycle": lifecycle,
            "science": science,
            "curve_rows": curve_rows,
            "curve_csv": {"path": str(curve_path), "sha256": sha256_file(curve_path), "rows": len(curve_rows)},
            "preview": preview,
            "q_i_status": "evidence_only",
            "q_n_status": "not_assessed",
            "production_eligibility": "not_evaluated",
        }
        (artifact_output / "science-artifact-report.json").write_text(json.dumps(artifact_report, indent=2, sort_keys=True, default=_json_default) + "\n", encoding="utf-8")
        artifacts.append(artifact_report)
    comparison = compare_artifacts(artifacts=artifacts, output_dir=output_dir, save_plan=save_plan, operators=operators)
    (output_dir / "interaction-calibration.json").write_text(json.dumps(calibration, indent=2, sort_keys=True, default=_json_default) + "\n", encoding="utf-8")
    report = {
        "schema": SCHEMA,
        "attempt_status": "completed_actual_read_only_audit",
        "claim_boundary": "typed Q-I lifecycle/reference evidence; Q-N and production are not assessed",
        "manifest": {"path": str(manifest_path), "sha256": sha256_file(manifest_path), "artifact_count": len(manifest)},
        "operators": {"path": str(operators_path), "sha256": sha256_file(operators_path)},
        "native_accounting": {"path": str(native_accounting_path), "sha256": sha256_file(native_accounting_path)},
        "scale_plan": {"path": str(scale_plan_path), "sha256": sha256_file(scale_plan_path)} if scale_plan_path else None,
        "partvtkout": {"path": str(partvtkout), "sha256": sha256_file(partvtkout)},
        "calibration": calibration,
        "artifacts": [{"artifact_id": item["artifact_id"], "path": str(output_dir / "artifacts" / item["artifact_id"] / "science-artifact-report.json"), "sha256": sha256_file(output_dir / "artifacts" / item["artifact_id"] / "science-artifact-report.json"), "lifecycle_status": item["lifecycle"]["status"], "missing_typed_fluid_count": item["lifecycle"]["lifecycle"]["terminal_missing_fluid_typed_count"], "contact_status": item["science"]["contact_first"]["status"]} for item in artifacts],
        "comparison": comparison,
        "resource": {"wall_seconds": time.monotonic() - started, "usage": _resource_delta(before, _resource_snapshot())},
        "q_i_status": "reference_evidence_complete; lifecycle findings are per artifact",
        "q_n_status": "not_assessed",
        "production_eligibility": "not_evaluated",
    }
    report_path = output_dir / "f4-science-audit-report.json"
    report["report"] = {"path": str(report_path)}
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True, default=_json_default) + "\n", encoding="utf-8")
    report["report"]["sha256"] = sha256_file(report_path)
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--operators", type=Path, required=True)
    parser.add_argument("--native-accounting", type=Path, required=True)
    parser.add_argument("--scale-plan", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--partvtkout", type=Path, required=True)
    parser.add_argument("--no-render", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = audit_manifest(
        manifest_path=args.manifest,
        operators_path=args.operators,
        native_accounting_path=args.native_accounting,
        scale_plan_path=args.scale_plan,
        output_dir=args.output,
        partvtkout=args.partvtkout,
        render=not args.no_render,
    )
    print(json.dumps({"report": report["report"], "artifacts": len(report["artifacts"]), "comparisons": report["comparison"]["comparison_count"], "q_n_status": report["q_n_status"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
