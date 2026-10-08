#!/usr/bin/env python3
"""Labels-only forward consumer for an already reconstructed typed HDF5.

The V37 raw/typed attempt produced a complete typed HDF5 before its V15 import
failed.  This additive worker consumes that typed artifact in a fresh labels
output namespace.  It verifies the typed file content SHA and stat only after
the parent I/O reservation, validates the identity/time/lifecycle contract,
loads V14/V15/V16 from the copied source paths, and computes labels from the
typed trajectory.

It never opens BI4/raw solver data and never reruns the converter.  Its report
therefore says typed_only_replay and raw_opened=false.  QI/QN/QE stay UNKNOWN
and this stage cannot establish a complete cold portable replay.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import stat
import sys
from typing import Any, Mapping, Sequence

SCHEMA = "ds02.stage2.f2-s1-typed-label-only-request.v1"
REPORT_SCHEMA = "ds02.stage2.f2-s1-typed-label-only-report.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
BASE_SCHEMA = "ds02.stage2.f2-native-raw-to-typed-to-label-request.v2"
V15_SCHEMA = "ds02.stage2.f2-s1-replay-request.v15"
SCRIPT = Path(__file__).resolve()


class TypedLabelsOnlyError(RuntimeError):
    """The typed-only source, identity, or label contract is unsafe."""


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key not in {"sha256", "report_sha256"}}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        default=str).encode("utf-8")).hexdigest()


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser()
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TypedLabelsOnlyError(f"cannot read JSON {target}: {error}") from error
    if not isinstance(value, dict):
        raise TypedLabelsOnlyError(f"JSON object required: {target}")
    return value


def write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser()
    if target.exists():
        raise TypedLabelsOnlyError(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    return target


def _require_sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in HEX64 for c in value):
        raise TypedLabelsOnlyError(f"{name} must be a lowercase SHA-256")
    return value


def _require_file(path: Any, role: str) -> Path:
    if not isinstance(path, str):
        raise TypedLabelsOnlyError(f"{role} path is missing")
    target = Path(path).expanduser()
    if not target.is_file():
        raise TypedLabelsOnlyError(f"{role} is missing: {target}")
    return target


def _stat_binding(path: Path, role: str) -> dict[str, Any]:
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise TypedLabelsOnlyError(f"{role} is not a regular file")
    return {"path": str(path), "bytes": int(info.st_size),
            "mtime_ns": int(info.st_mtime_ns),
            "mode_bits": int(stat.S_IMODE(info.st_mode))}


def _module_binding(raw: Mapping[str, Any], role: str) -> dict[str, Any]:
    path = _require_file(raw.get("path"), role)
    expected = _require_sha(raw.get("sha256"), f"{role}.sha256")
    actual = sha256_file(path)
    if actual != expected:
        raise TypedLabelsOnlyError(f"{role} SHA differs")
    value = dict(raw)
    value.update(_stat_binding(path, role))
    value["sha256"] = expected
    return value


def _find_source(sources: Sequence[Any], role: str) -> dict[str, Any]:
    values = [dict(item) for item in sources
              if isinstance(item, Mapping) and item.get("role") == role]
    if len(values) != 1:
        raise TypedLabelsOnlyError(f"source role is not unique: {role}")
    path = _require_file(values[0].get("path"), role)
    expected = _require_sha(values[0].get("sha256"), f"{role}.sha256")
    if sha256_file(path) != expected:
        raise TypedLabelsOnlyError(f"{role} SHA differs")
    values[0].update(_stat_binding(path, role))
    return values[0]


def _base_metadata(base_path: Path | str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    base_file = _require_file(str(base_path), "base V2 request")
    base = load_json(base_file)
    if base.get("schema") != BASE_SCHEMA:
        raise TypedLabelsOnlyError("base request schema differs")
    if base.get("role") != "DEVELOPMENT" or base.get("model_invoked") is not False:
        raise TypedLabelsOnlyError("base request is not model-free DEVELOPMENT")
    if base.get("cfd_invoked") is not False or base.get("qualification") != UNKNOWN:
        raise TypedLabelsOnlyError("base request qualification/CFD flags differ")
    modules = base.get("modules")
    if not isinstance(modules, Mapping):
        raise TypedLabelsOnlyError("base modules closure is missing")
    checked_modules = {}
    for role in ("v14_operator", "v15_operator", "v16_operator"):
        checked_modules[role] = _module_binding(modules.get(role), role)
    v15_source = _find_source(base.get("source_files", []), "v15_replay_request")
    v15_request = load_json(v15_source["path"])
    if v15_request.get("schema") != V15_SCHEMA:
        raise TypedLabelsOnlyError("bound V15 request schema differs")
    if v15_request.get("role") != "DEVELOPMENT" or v15_request.get("model_invoked") is not False:
        raise TypedLabelsOnlyError("bound V15 request is not model-free DEVELOPMENT")
    if v15_request.get("qualification") != UNKNOWN:
        raise TypedLabelsOnlyError("bound V15 request qualification differs")
    return base, {"path": str(base_file), "sha256": sha256_file(base_file),
                  "bytes": int(base_file.stat().st_size), "mtime_ns": int(base_file.stat().st_mtime_ns)}, {
        "modules": checked_modules, "v15_source": v15_source,
        "v15_request": v15_request,
    }


def _typed_contract(base: Mapping[str, Any], report: Mapping[str, Any],
                    typed_h5: Path) -> dict[str, Any]:
    contract = base.get("typed_output_contract")
    if not isinstance(contract, Mapping):
        raise TypedLabelsOnlyError("typed_output_contract is missing")
    frames = int(contract.get("frames", -1))
    particles = int(contract.get("particles", -1))
    times = contract.get("expected_times_s")
    if frames != 401 or particles <= 0 or not isinstance(times, list) or len(times) != frames:
        raise TypedLabelsOnlyError("typed frame/particle/time contract is incomplete")
    if any(not isinstance(x, (int, float)) or not math.isfinite(float(x)) for x in times):
        raise TypedLabelsOnlyError("typed expected times are not finite")
    expected_sha = _require_sha(report.get("output_sha256"), "converter_report.output_sha256")
    raw = report.get("source_provenance", {}).get("raw_tree", {})
    if not isinstance(raw, Mapping):
        raise TypedLabelsOnlyError("converter report raw-tree provenance is missing")
    raw_sha = _require_sha(raw.get("after_tree_sha256"), "converter raw tree SHA")
    raw_count = int(raw.get("after_file_count", -1))
    raw_binding = base.get("raw_binding")
    if not isinstance(raw_binding, Mapping):
        raise TypedLabelsOnlyError("base raw binding is missing")
    if raw_count != int(raw_binding.get("expected_file_count", -2)):
        raise TypedLabelsOnlyError("converter raw file count differs from frozen V37 binding")
    if raw_sha != raw_binding.get("expected_raw_tree_sha256"):
        raise TypedLabelsOnlyError("converter raw tree SHA differs from frozen V37 binding")
    if report.get("schema") != "ds-data-02.bi4-direct-conversion.v1" or report.get("conversion_status") != "completed":
        raise TypedLabelsOnlyError("converter report is not completed V37 conversion evidence")
    if not typed_h5.is_file() or typed_h5.stat().st_size <= 0:
        raise TypedLabelsOnlyError("typed HDF5 is missing/empty")
    identities = {}
    for key in ("fluid_identity_ids", "fluid_identity_zones", "fluid_identity_mks"):
        value = contract.get(key)
        if value is not None and (not isinstance(value, list) or
                                  len(value) != int(base["cohort"]["expected_initial_fluid_count"])):
            raise TypedLabelsOnlyError(f"typed identity contract is malformed: {key}")
        identities[key] = value
    if not any(value is not None for value in identities.values()):
        identity_binding = "derive_from_typed_initial_axis_and_compare_frozen_source_identity_sha256"
    elif not all(value is not None for value in identities.values()):
        raise TypedLabelsOnlyError("typed identity vectors must be all present or all deferred")
    else:
        identity_binding = "exact_declared_zone_id_mk_vectors"
    denominator = base.get("initial_mass_denominator")
    if not isinstance(denominator, Mapping):
        raise TypedLabelsOnlyError("initial mass denominator is missing")
    if not math.isclose(float(denominator["denominator_kg"]), 21.114001002861187,
                        rel_tol=0.0, abs_tol=5e-8):
        raise TypedLabelsOnlyError("F2 frozen initial denominator differs")
    summary = report.get("lifecycle", {}).get("frame_summary")
    if not isinstance(summary, list) or len(summary) != frames:
        raise TypedLabelsOnlyError("converter lifecycle frame summary is incomplete")
    return {
        "frames": frames, "particles": particles, "expected_times_s": list(times),
        "identity": identities,
        "identity_binding": identity_binding,
        "identity_sha256": str(base["cohort"]["source_identity_set_sha256"]),
        "fluid_count": int(base["cohort"]["expected_initial_fluid_count"]),
        "initial_mk_codes": list(base["cohort"]["initial_mk_codes"]),
        "initial_type_code": int(base["cohort"]["initial_type_code"]),
        "denominator_kg": float(denominator["denominator_kg"]),
        "initial_missing_mass_kg": float(denominator["initial_missing_mass_kg"]),
        "later_missing_mass_kg": float(denominator["later_missing_mass_kg"]),
        "typed_expected_sha256": expected_sha,
        "typed_expected_bytes_stat": int(typed_h5.stat().st_size),
        "raw_tree_sha256": raw_sha, "raw_file_count": raw_count,
        "converter_report_status": "COMPLETED_RAW_TO_TYPED; LABELS_ONLY_FOLLOW_ON",
        "lifecycle_summary_sha256": hashlib.sha256(
            json.dumps(summary, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
    }


def build_request(*, base_request: Path | str, converter_report: Path | str,
                  typed_h5: Path | str, output: Path | str,
                  output_root: Path | str) -> dict[str, Any]:
    base, base_binding, closure = _base_metadata(base_request)
    report_path = _require_file(str(converter_report), "converter report")
    report = load_json(report_path)
    report_binding = {"path": str(report_path), "sha256": sha256_file(report_path),
                      "bytes": int(report_path.stat().st_size),
                      "mtime_ns": int(report_path.stat().st_mtime_ns)}
    typed = _require_file(str(typed_h5), "typed HDF5")
    output_path = Path(output_root).expanduser()
    if output_path.exists():
        raise TypedLabelsOnlyError("labels-only output root must be fresh")
    contract = _typed_contract(base, report, typed)
    request: dict[str, Any] = {
        "schema": SCHEMA, "request_id": str(base.get("request_id", "f2-v37")) + "-typed-labels-only-v1",
        "role": "DEVELOPMENT", "status": "READY_FOR_PARENT_TYPED_LABEL_GUARD",
        "case_identity": copy.deepcopy(base.get("case_identity", {})),
        "base_v2_request": base_binding,
        "frozen_v15_request": {
            "path": closure["v15_source"]["path"], "sha256": closure["v15_source"]["sha256"],
            "bytes": closure["v15_source"]["bytes"], "mtime_ns": closure["v15_source"]["mtime_ns"],
        },
        "modules": closure["modules"],
        "converter_report": report_binding,
        "typed_input": {
            "path": str(typed), "producer_report_output_path": report.get("output_hdf5"),
            "bytes_at_build": int(typed.stat().st_size), "mtime_ns_at_build": int(typed.stat().st_mtime_ns),
            "expected_sha256": contract["typed_expected_sha256"],
            "content_sha256_phase": "PARENT_AFTER_RESERVE_AND_WORKER_BEFORE_HDF5_READ",
            "source_kind": "V37 completed native BI4-to-typed artifact",
        },
        "raw_provenance": {
            "raw_opened_by_this_stage": False, "raw_file_count": contract["raw_file_count"],
            "expected_raw_tree_sha256": contract["raw_tree_sha256"],
            "producer_conversion_report_sha256": report_binding["sha256"],
            "source_scope": "V37 raw-tree gate and converter evidence only; no new raw read",
        },
        "typed_contract": contract,
        "v15_request": closure["v15_request"],
        "output_root": str(output_path),
        "execution": {
            "command": ["<venv-python>", "-B", "-I", str(SCRIPT), "run",
                        "--request", "<this-request>", "--io-slot-approved",
                        "--parent-pid", "<parent-pid>", "--output-dir", str(output_path)],
            "requires_parent_stage2guard": True,
            "typed_h5_content_hash_after_reserve": True,
            "raw_opened": False, "hdf5_opened": True,
            "model_invoked": False, "cfd_invoked": False,
            "original_path_fallback": "FORBIDDEN",
            "qualification": dict(UNKNOWN),
        },
        "resource_request": {
            "cpu_cores": 1, "max_wall_seconds": 2400,
            "estimated_typed_hdf5_read_bytes": int(typed.stat().st_size),
            "estimated_output_bytes": 64 * 1024 * 1024,
            "peak_memory_estimate_bytes": 700 * 1024 * 1024,
            "raw_read_bytes": 0, "bi4_read": False,
            "storage_scope": "fresh labels-only output root",
        },
        "raw_opened": False, "hdf5_opened": False,
        "model_invoked": False, "cfd_invoked": False,
        "qualification": dict(UNKNOWN),
        "limitations": [
            "This stage consumes a completed V37 typed HDF5 and does not rerun raw BI4 conversion.",
            "It is typed-only development evidence; complete cold portable replay remains pending V38.",
            "The V37 converter report/raw-tree provenance is preserved; it is not a new raw-source proof.",
        ],
    }
    request["sha256"] = canonical_sha(request)
    path = write_new(output, request)
    return {"status": request["status"], "request": str(path),
            "sha256": request["sha256"], "typed_expected_sha256": contract["typed_expected_sha256"],
            "typed_bytes_at_build": contract["typed_expected_bytes_stat"],
            "raw_opened": False, "hdf5_opened": False, "qualification": dict(UNKNOWN)}


def _load_request(path: Path | str) -> dict[str, Any]:
    request_path = _require_file(str(path), "labels-only request")
    request = load_json(request_path)
    if request.get("schema") != SCHEMA or request.get("sha256") != canonical_sha(request):
        raise TypedLabelsOnlyError("labels-only request schema/SHA differs")
    if request.get("role") != "DEVELOPMENT" or request.get("model_invoked") is not False:
        raise TypedLabelsOnlyError("labels-only request is not model-free DEVELOPMENT")
    if request.get("cfd_invoked") is not False or request.get("qualification") != UNKNOWN:
        raise TypedLabelsOnlyError("labels-only request flags differ")
    if request.get("raw_opened") is not False or request.get("execution", {}).get("raw_opened") is not False:
        raise TypedLabelsOnlyError("labels-only request cannot claim raw input")
    _require_sha(request.get("typed_input", {}).get("expected_sha256"), "typed expected SHA")
    return request


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise TypedLabelsOnlyError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _spans(indices: Any) -> list[tuple[int, int, int, int]]:
    import numpy as np
    if len(indices) == 0:
        return []
    starts = [0] + list(np.flatnonzero(np.diff(indices) != 1) + 1)
    stops = starts[1:] + [len(indices)]
    return [(a, b, int(indices[a]), int(indices[b - 1]) + 1) for a, b in zip(starts, stops)]


def _selected(dataset: Any, frame: int, indices: Any, width: int | None = None) -> Any:
    import numpy as np
    shape = (len(indices),) if width is None else (len(indices), width)
    result = np.empty(shape, dtype=dataset.dtype)
    for left, right, source_left, source_right in _spans(indices):
        result[left:right] = dataset[frame, source_left:source_right]
    return result


def _identity_sha(zones: Any, ids: Any) -> str:
    import numpy as np
    order = np.lexsort((ids.astype("<i8"), zones.astype("<i8")))
    return hashlib.sha256(np.stack([
        zones[order].astype("<i8"), ids[order].astype("<i8")
    ], axis=1).tobytes()).hexdigest()


def _trajectory_from_typed(request: Mapping[str, Any], typed_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    import h5py
    import numpy as np
    contract = request["typed_contract"]
    frames, particles = int(contract["frames"]), int(contract["particles"])
    with h5py.File(typed_path, "r") as h5:
        required = ("time", "particle_id", "particle_zone", "valid", "position",
                    "velocity", "mass", "initial_type", "initial_mk", "initial_mass")
        missing = [name for name in required if name not in h5]
        if missing:
            raise TypedLabelsOnlyError(f"typed HDF5 missing datasets: {missing}")
        if tuple(h5["time"].shape) != (frames,) or tuple(h5["particle_id"].shape) != (particles,):
            raise TypedLabelsOnlyError("typed time/identity shapes differ")
        if tuple(h5["particle_zone"].shape) != (particles,):
            raise TypedLabelsOnlyError("typed particle_zone shape differs")
        for name in ("valid", "mass"):
            if tuple(h5[name].shape) != (frames, particles):
                raise TypedLabelsOnlyError(f"typed {name} shape differs")
        for name in ("position", "velocity"):
            if tuple(h5[name].shape) != (frames, particles, 3):
                raise TypedLabelsOnlyError(f"typed {name} shape differs")
        if tuple(h5["initial_type"].shape) != (particles,) or tuple(h5["initial_mk"].shape) != (particles,):
            raise TypedLabelsOnlyError("typed initial identity shape differs")
        if h5.attrs.get("identity_key") != "(Zone,Idp)" or not bool(h5.attrs.get("conversion_complete")):
            raise TypedLabelsOnlyError("typed identity/conversion attributes are not closed")
        times = np.asarray(h5["time"][...], dtype="f8")
        expected_times = np.asarray(contract["expected_times_s"], dtype="f8")
        if not np.allclose(times, expected_times, rtol=0.0, atol=2e-8):
            raise TypedLabelsOnlyError("typed time axis differs from CURRENT-bound contract")
        if not np.all(np.diff(times) > 0) or times[0] != 0.0 or times[-1] <= 4.0:
            raise TypedLabelsOnlyError("typed time axis is not complete 0..4s")
        ids = np.asarray(h5["particle_id"][...], dtype="<u4")
        zones = np.asarray(h5["particle_zone"][...], dtype="<i2")
        if not np.array_equal(ids, np.arange(particles, dtype="<u4")):
            raise TypedLabelsOnlyError("typed particle ID axis differs from GenCase axis")
        initial_type = np.asarray(h5["initial_type"][...], dtype="i1")
        initial_mk = np.asarray(h5["initial_mk"][...], dtype="<i2")
        initial_mass = np.asarray(h5["initial_mass"][...], dtype="f4")
        selected = np.flatnonzero(
            (initial_type == int(contract["initial_type_code"])) &
            np.isin(initial_mk, np.asarray(contract["initial_mk_codes"], dtype="<i2")))
        if len(selected) != int(contract["fluid_count"]):
            raise TypedLabelsOnlyError("typed Type/MK fluid count differs")
        order = np.lexsort((ids[selected], zones[selected]))
        selected = selected[order]
        declared_ids = contract["identity"].get("fluid_identity_ids")
        declared_zones = contract["identity"].get("fluid_identity_zones")
        declared_mks = contract["identity"].get("fluid_identity_mks")
        if declared_ids is not None:
            expected_ids = np.asarray(declared_ids, dtype="<u4")
            expected_zones = np.asarray(declared_zones, dtype="<i2")
            expected_mks = np.asarray(declared_mks, dtype="<i2")
            if not (np.array_equal(ids[selected], expected_ids) and
                    np.array_equal(zones[selected], expected_zones) and
                    np.array_equal(initial_mk[selected], expected_mks)):
                raise TypedLabelsOnlyError("typed identity axis differs from frozen cohort")
        if _identity_sha(zones[selected], ids[selected]) != contract["identity_sha256"]:
            raise TypedLabelsOnlyError("typed identity SHA differs from frozen cohort")
        selected_mass = initial_mass[selected].astype("f8")
        if not np.isfinite(selected_mass).all() or np.any(selected_mass <= 0):
            raise TypedLabelsOnlyError("typed initial fluid mass is invalid")
        if not math.isclose(float(selected_mass.sum()), float(contract["denominator_kg"]),
                            rel_tol=0.0, abs_tol=5e-8):
            raise TypedLabelsOnlyError("typed initial mass denominator differs")
        positions = np.empty((frames, len(selected), 3), dtype="f4")
        velocities = np.empty_like(positions)
        masses = np.empty((frames, len(selected)), dtype="f4")
        valid = np.empty((frames, len(selected)), dtype=bool)
        for frame in range(frames):
            valid[frame] = np.asarray(h5["valid"][frame, selected], dtype=bool)
            positions[frame] = _selected(h5["position"], frame, selected, width=3)
            velocities[frame] = _selected(h5["velocity"], frame, selected, width=3)
            masses[frame] = _selected(h5["mass"], frame, selected)
            active = valid[frame]
            if not np.isfinite(positions[frame][active]).all() or not np.isfinite(velocities[frame][active]).all():
                raise TypedLabelsOnlyError(f"typed active position/velocity nonfinite at frame {frame}")
            if not np.isfinite(masses[frame][active]).all():
                raise TypedLabelsOnlyError(f"typed active mass nonfinite at frame {frame}")
            if np.isfinite(positions[frame][~active]).any() or np.isfinite(velocities[frame][~active]).any() or np.isfinite(masses[frame][~active]).any():
                raise TypedLabelsOnlyError(f"typed inactive fields falsely observed at frame {frame}")
        trajectory = {
            "time": times, "position": positions, "velocity": velocities, "mass": masses,
            "valid": valid, "initial_position": positions[0].copy(),
            "initial_type": initial_type[selected], "initial_mk": initial_mk[selected],
            "particle_zone": zones[selected], "particle_id": ids[selected],
            "initial_mass": selected_mass.astype("f4"),
        }
        return trajectory, {
            "frames": frames, "particles": particles, "selected_particles": len(selected),
            "identity_sha256": contract["identity_sha256"],
            "typed_fields_validated": ["time", "particle_id", "particle_zone", "valid",
                                       "position", "velocity", "mass", "initial_type",
                                       "initial_mk", "initial_mass"],
            "raw_opened": False,
        }


def _load_bound_operators(request: Mapping[str, Any]) -> tuple[Any, Any]:
    modules = request["modules"]
    v14_path = _require_file(modules["v14_operator"]["path"], "v14 operator")
    v15_path = _require_file(modules["v15_operator"]["path"], "v15 operator")
    v16_path = _require_file(modules["v16_operator"]["path"], "v16 operator")
    for role, path in (("v14_operator", v14_path), ("v15_operator", v15_path), ("v16_operator", v16_path)):
        if sha256_file(path) != modules[role]["sha256"]:
            raise TypedLabelsOnlyError(f"{role} SHA differs")
    _load_module(v14_path, "ds_data02_stage2_f2_replay_v14")
    v15 = _load_module(v15_path, "_ds02_typed_only_v15")
    v16 = _load_module(v16_path, "_ds02_typed_only_v16")
    return v15, v16


def run(request_path: Path | str, *, output_dir: Path | str,
        io_slot_approved: bool, parent_pid: int | None = None) -> dict[str, Any]:
    request = _load_request(request_path)
    if not io_slot_approved:
        raise TypedLabelsOnlyError("run requires parent --io-slot-approved")
    if parent_pid is not None and (parent_pid <= 1 or not Path(f"/proc/{parent_pid}").exists()):
        raise TypedLabelsOnlyError("parent guard process is not alive")
    target = Path(output_dir).expanduser()
    if target.exists():
        raise TypedLabelsOnlyError(f"refusing existing output directory: {target}")
    target.mkdir(parents=True, exist_ok=False)
    typed_item = request["typed_input"]
    typed_path = _require_file(typed_item["path"], "typed HDF5")
    pre = _stat_binding(typed_path, "typed HDF5")
    expected_bytes = int(typed_item["bytes_at_build"])
    expected_sha = _require_sha(typed_item["expected_sha256"], "typed expected SHA")
    if pre["bytes"] != expected_bytes:
        raise TypedLabelsOnlyError("typed HDF5 byte stat changed before guarded read")
    observed_sha = sha256_file(typed_path)
    post = _stat_binding(typed_path, "typed HDF5")
    if observed_sha != expected_sha:
        raise TypedLabelsOnlyError("typed HDF5 content SHA differs from V37 converter report")
    if pre["bytes"] != post["bytes"] or pre["mtime_ns"] != post["mtime_ns"]:
        raise TypedLabelsOnlyError("typed HDF5 stat changed during guarded hash/read")
    v15, v16 = _load_bound_operators(request)
    v15_request = load_json(request["frozen_v15_request"]["path"])
    if v15_request.get("schema") != V15_SCHEMA or sha256_file(request["frozen_v15_request"]["path"]) != request["frozen_v15_request"]["sha256"]:
        raise TypedLabelsOnlyError("frozen V15 request binding differs")
    trajectory, typed_validation = _trajectory_from_typed(request, typed_path)
    result = v15.replay_trajectory_v15(trajectory, v15_request)
    result["typed_only_replay"] = True
    result["raw_opened"] = False
    result["typed_input_binding"] = {
        "path": str(typed_path), "bytes": pre["bytes"], "sha256": observed_sha,
        "producer_converter_report": request["converter_report"],
    }
    result_path = write_new(target / "typed-label-result-v15.json", result)
    v16_value = v16.forward_result(
        result,
        unknown_endpoint_mass_kg=float(request["typed_contract"]["later_missing_mass_kg"]),
        endpoint_scope="F2_S1_INITIAL_OUTSIDE_HALFSPACE_LATER_MISSING_ENDPOINTS_ONLY",
    )
    v16_value["typed_only_replay"] = True
    v16_value["raw_opened"] = False
    v16_path = write_new(target / "typed-label-result-v16.json", v16_value)
    report = {
        "schema": REPORT_SCHEMA, "status": "COMPLETE_TYPED_ONLY_LABELS_DEVELOPMENT_UNKNOWN",
        "request": {"path": str(Path(request_path).expanduser()), "sha256": sha256_file(request_path)},
        "typed_input": {"path": str(typed_path), "pre_stat": pre, "post_stat": post,
                        "sha256": observed_sha, "content_sha256_phase": "AFTER_PARENT_RESERVE"},
        "v37_provenance": {
            "base_v2_request": request["base_v2_request"],
            "converter_report": request["converter_report"],
            "raw_tree_sha256": request["raw_provenance"]["expected_raw_tree_sha256"],
            "raw_file_count": request["raw_provenance"]["raw_file_count"],
            "raw_reopened": False,
        },
        "typed_validation": typed_validation,
        "labels": {"v15": {"path": str(result_path), "sha256": sha256_file(result_path)},
                   "v16": {"path": str(v16_path), "sha256": sha256_file(v16_path)}},
        "execution_boundary": {
            "raw_opened": False, "typed_hdf5_opened": True,
            "converter_invoked": False, "label_operator_invoked": True,
            "model_invoked": False, "cfd_invoked": False,
            "parent_stage2guard_required": True,
        },
        "model_invoked": False, "cfd_invoked": False,
        "qualification": dict(UNKNOWN),
        "limitations": [
            "typed-only follow-on; no raw BI4 was reopened",
            "V37 raw-tree and converter evidence is provenance, not a new cold replay",
            "QI/QN/QE remain UNKNOWN until the parent scientific review",
        ],
    }
    report["sha256"] = canonical_sha(report)
    report_path = write_new(target / "typed-label-only-report-v1.json", report)
    return {"status": report["status"], "report": str(report_path),
            "sha256": report["sha256"], "raw_opened": False,
            "typed_hdf5_opened": True, "qualification": dict(UNKNOWN)}


def preflight(request_path: Path | str, output: Path | str) -> dict[str, Any]:
    request = _load_request(request_path)
    typed_path = _require_file(request["typed_input"]["path"], "typed HDF5")
    if typed_path.stat().st_size != int(request["typed_input"]["bytes_at_build"]):
        raise TypedLabelsOnlyError("typed HDF5 stat differs in metadata preflight")
    result = {
        "schema": "ds02.stage2.f2-s1-typed-label-only-preflight.v1",
        "status": "READY_FOR_PARENT_TYPED_LABEL_GUARD",
        "request": {"path": str(Path(request_path).expanduser()), "sha256": sha256_file(request_path)},
        "typed_input": {"path": str(typed_path), "bytes": int(typed_path.stat().st_size),
                        "content_hash_read": False,
                        "expected_sha256": request["typed_input"]["expected_sha256"]},
        "raw_opened": False, "hdf5_or_bi4_read": False,
        "model_invoked": False, "cfd_invoked": False, "qualification": dict(UNKNOWN),
    }
    result["sha256"] = canonical_sha(result)
    write_new(output, result)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--base-request", type=Path, required=True)
    build.add_argument("--converter-report", type=Path, required=True)
    build.add_argument("--typed-h5", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--output-root", type=Path, required=True)
    pre = sub.add_parser("preflight")
    pre.add_argument("--request", type=Path, required=True)
    pre.add_argument("--output", type=Path, required=True)
    runner = sub.add_parser("run")
    runner.add_argument("--request", type=Path, required=True)
    runner.add_argument("--output-dir", type=Path, required=True)
    runner.add_argument("--io-slot-approved", action="store_true")
    runner.add_argument("--parent-pid", type=int)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-request":
            value = build_request(base_request=args.base_request, converter_report=args.converter_report,
                                  typed_h5=args.typed_h5, output=args.output, output_root=args.output_root)
        elif args.command == "preflight":
            value = preflight(args.request, args.output)
        else:
            value = run(args.request, output_dir=args.output_dir,
                        io_slot_approved=args.io_slot_approved, parent_pid=args.parent_pid)
    except (TypedLabelsOnlyError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"f2 typed labels-only v1: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
