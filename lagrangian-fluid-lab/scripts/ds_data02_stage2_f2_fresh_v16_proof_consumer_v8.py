#!/usr/bin/env python3
"""Guarded, JSON-only independent verifier for a fresh F2 V16 result.

The cold native worker and its HDF5/BI4 inputs are deliberately outside this
module.  This consumer is a small follow-on stage: after the parent has
reserved the I/O slot, it reads and hashes one relocated V16 JSON result,
checks the source/identity/mass/time/censor contracts, and writes a compact
proof.  It never opens HDF5, BI4, raw arrays, a model, or CFD.  It does not
create or mutate a Stage2 ledger; the supervising parent owns that accounting.

The contract is intentionally explicit because an old V16 proof must not be
reused for a new result.  A request binds the exact result SHA, relocated
output root, expected CURRENT/H5/source hashes, identity axis, initial mass
denominator, saved timeline, and quality boundary.  Missing or ambiguous
observations remain in the proof; they are not converted to scientific credit.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import signal
import struct
import sys
import time
from typing import Any, Mapping, Sequence


REQUEST_SCHEMA = "ds02.stage2.f2-fresh-v16-proof-consumer-request.v8"
PROOF_SCHEMA = "ds02.stage2.f2-fresh-v16-proof.v8"
RESULT_SCHEMA = "ds02.stage2.f2-s1-replay-result.v16"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
FIRST_PASSAGE_STATUSES = {
    "observed", "right_censored", "failed_before_observation",
    "initially_inside", "ambiguous_multiple_crossing",
}
RECEIVER_STATUSES = {
    "observed", "right_censored", "failed_before_observation",
    "initially_inside", "ambiguous_multiple_crossing",
}
DESTINATION_STATUSES = {
    "inside_receiver_volume", "outside_receiver_volume", "unknown_final_destination",
}
OLD_PROOF_SHA256 = {
    # The old proof is a historical artifact and is never accepted as the
    # proof for a new relocated V16 result.
    "2b71dcb5370b9cdbd745ece877e892a6f30871207e9351c102cfb9720422fb47",
}
PR_SET_PDEATHSIG = 1


class ProofConsumerError(RuntimeError):
    """Raised for a malformed, stale, or unsafe JSON-only proof input."""


class ProofDeadline(ProofConsumerError):
    pass


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path | str, *, max_bytes: int | None = None) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    with Path(path).open("rb") as stream:
        while True:
            block = stream.read(4 * 1024 * 1024)
            if not block:
                break
            total += len(block)
            if max_bytes is not None and total > max_bytes:
                raise ProofConsumerError(
                    f"JSON result exceeds the bound {max_bytes} bytes: {path}"
                )
            digest.update(block)
    return digest.hexdigest(), total


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProofConsumerError(f"{name} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ProofConsumerError(f"{name} must be finite")
    return number


def _finite_nonnegative(value: Any, name: str) -> float:
    number = _finite(value, name)
    if number < 0:
        raise ProofConsumerError(f"{name} must be nonnegative")
    return number


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in HEX64 for ch in value):
        raise ProofConsumerError(f"{name} must be a lowercase SHA-256")
    return value


def _load_object(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProofConsumerError(f"cannot read JSON object {target}: {error}") from error
    if not isinstance(value, dict):
        raise ProofConsumerError(f"JSON object required: {target}")
    return value


def _read_result(path: Path, max_bytes: int) -> tuple[dict[str, Any], str, int]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise ProofConsumerError(f"cannot read V16 result {path}: {error}") from error
    if len(raw) > max_bytes:
        raise ProofConsumerError(f"V16 result exceeds max_result_bytes={max_bytes}")
    digest = sha256_bytes(raw)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ProofConsumerError(f"V16 result is not UTF-8 JSON: {error}") from error
    if not isinstance(value, dict):
        raise ProofConsumerError("V16 result must be a JSON object")
    return value, digest, len(raw)


def _under(path: Path | str, root: Path | str) -> bool:
    candidate = os.path.normpath(str(Path(path).expanduser().resolve()))
    base = os.path.normpath(str(Path(root).expanduser().resolve()))
    return candidate == base or candidate.startswith(base.rstrip(os.sep) + os.sep)


def _stat(path: Path) -> dict[str, Any]:
    try:
        value = path.stat()
    except OSError as error:
        raise ProofConsumerError(f"cannot stat {path}: {error}") from error
    if not path.is_file():
        raise ProofConsumerError(f"bound result is not a regular file: {path}")
    return {"bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns),
            "mode": int(value.st_mode & 0o777)}


def _unknown_quality(value: Any, name: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ProofConsumerError(f"{name} must be an object with QI/QN/QE UNKNOWN")
    observed = {key: value.get(key) for key in UNKNOWN}
    if observed != UNKNOWN:
        raise ProofConsumerError(f"{name} must keep QI/QN/QE UNKNOWN")
    if "qualification" in value and value.get("qualification") != "UNKNOWN":
        raise ProofConsumerError(f"{name}.qualification must remain UNKNOWN")
    return dict(UNKNOWN)


def _identity_sha(labels: Sequence[Mapping[str, Any]]) -> str:
    pairs: list[tuple[int, int]] = []
    for index, label in enumerate(labels):
        if not isinstance(label, Mapping):
            raise ProofConsumerError(f"labels[{index}] must be an object")
        try:
            zone, idp = int(label["zone"]), int(label["idp"])
        except (KeyError, TypeError, ValueError) as error:
            raise ProofConsumerError(f"labels[{index}] lacks integer Zone/Idp") from error
        pairs.append((zone, idp))
    if len(set(pairs)) != len(pairs):
        raise ProofConsumerError("labels contain duplicate (Zone,Idp) identities")
    pairs.sort()
    payload = b"".join(struct.pack("<qq", zone, idp) for zone, idp in pairs)
    return hashlib.sha256(payload).hexdigest()


def _path_audit(value: Any, *, original_roots: Sequence[Path], allowed_roots: Sequence[Path],
                context: tuple[str, ...] = ()) -> dict[str, Any]:
    """Audit absolute path values without opening any referenced path.

    A path nested under source/provenance fields is recorded as provenance; it
    is not opened by this worker.  Any original path in an actionable field,
    or any unbound absolute path outside the relocated roots, is rejected.
    """
    provenance: list[str] = []
    external: list[str] = []
    original_hits: list[str] = []
    provenance_keys = {"source_binding", "source_report", "provenance", "source_provenance"}

    def visit(item: Any, parents: tuple[str, ...]) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                visit(child, parents + (str(key),))
            return
        if isinstance(item, list):
            for child in item:
                visit(child, parents)
            return
        if not isinstance(item, str) or not item.startswith(os.sep):
            return
        try:
            path = Path(item).expanduser().resolve()
        except OSError:
            path = Path(item)
        is_provenance = any(key.lower() in provenance_keys for key in parents)
        if any(_under(path, root) for root in original_roots):
            if is_provenance:
                provenance.append(str(path))
            else:
                original_hits.append(str(path))
            return
        if is_provenance:
            provenance.append(str(path))
        elif not any(_under(path, root) for root in allowed_roots):
            external.append(str(path))

    visit(value, context)
    return {"provenance_paths": sorted(set(provenance)),
            "actionable_original_path_hits": sorted(set(original_hits)),
            "unbound_absolute_paths": sorted(set(external))}


def _pdeathsig(parent_pid: int) -> bool:
    """Install PDEATHSIG and fail closed if the parent changed."""
    if os.getppid() != int(parent_pid):
        raise ProofConsumerError("direct parent changed before JSON-only proof run")
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        result = int(libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0))
    except (AttributeError, OSError) as error:
        raise ProofConsumerError(f"cannot install parent-death signal: {error}") from error
    if result != 0 or os.getppid() != int(parent_pid):
        raise ProofConsumerError("parent-death binding was not established")
    return True


def _alarm_handler(signum: int, frame: Any) -> None:
    raise ProofDeadline("JSON-only proof consumer exceeded its parent deadline")


def _begin_timer(seconds: float) -> Any:
    if not math.isfinite(seconds) or seconds <= 0:
        raise ProofConsumerError("max_wall_seconds must be finite and positive")
    previous = signal.signal(signal.SIGALRM, _alarm_handler)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    return previous


def _end_timer(previous: Any) -> None:
    signal.setitimer(signal.ITIMER_REAL, 0.0)
    signal.signal(signal.SIGALRM, previous)


def _resource_snapshot() -> dict[str, Any]:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    rss = int(usage.ru_maxrss)
    if sys.platform != "darwin":
        rss *= 1024
    return {"user_seconds": float(usage.ru_utime),
            "system_seconds": float(usage.ru_stime),
            "max_rss_observed_bytes": rss}


def _compare_float(actual: Any, expected: Any, name: str, tolerance: float) -> float:
    left, right = _finite(actual, name), _finite(expected, f"expected {name}")
    if abs(left - right) > tolerance:
        raise ProofConsumerError(f"{name} differs: {left!r} != {right!r} (tol={tolerance})")
    return left


def _validate_request(request: Mapping[str, Any], *, verify_result_stat: bool) -> dict[str, Any]:
    if request.get("schema") != REQUEST_SCHEMA:
        raise ProofConsumerError(f"unsupported request schema: {request.get('schema')!r}")
    if request.get("role") != "DEVELOPMENT":
        raise ProofConsumerError("proof consumer request must remain DEVELOPMENT")
    if request.get("status") not in {"PENDING_PARENT_IO_SLOT", "READY_FOR_PARENT_GUARD"}:
        raise ProofConsumerError("proof consumer request is not parent-guard ready")
    if request.get("model_invoked") is not False or request.get("cfd_invoked") is not False:
        raise ProofConsumerError("model/CFD invocation is forbidden")
    _unknown_quality(request.get("quality", request.get("qualification")), "request quality")
    if request.get("ledger_mutated") is not False:
        raise ProofConsumerError("JSON-only consumer cannot own or mutate a ledger")
    if request.get("sha256") != canonical_sha(request):
        raise ProofConsumerError("proof consumer request canonical SHA differs")

    execution = request.get("execution")
    if not isinstance(execution, Mapping):
        raise ProofConsumerError("execution contract is required")
    max_wall = _finite(execution.get("max_wall_seconds"), "execution.max_wall_seconds")
    max_result_bytes = execution.get("max_result_bytes")
    if isinstance(max_result_bytes, bool) or not isinstance(max_result_bytes, int) or max_result_bytes <= 0:
        raise ProofConsumerError("execution.max_result_bytes must be a positive integer")
    if execution.get("read_hdf5_or_bi4") is not False or execution.get("raw_opened") is not False:
        raise ProofConsumerError("JSON-only execution flags are not closed")

    result_binding = request.get("result")
    if not isinstance(result_binding, Mapping) or not isinstance(result_binding.get("path"), str):
        raise ProofConsumerError("result.path binding is required")
    result_source_path = Path(result_binding["path"]).expanduser()
    if result_source_path.is_symlink():
        raise ProofConsumerError("relocated result must not be a symlink")
    result_path = result_source_path.resolve()
    if not result_path.is_file():
        raise ProofConsumerError("relocated result must be an existing regular file")
    expected_result_sha = _sha(result_binding.get("sha256"), "result.sha256")
    if expected_result_sha in OLD_PROOF_SHA256:
        raise ProofConsumerError("historical V16 proof SHA is forbidden for a fresh result")
    declared_bytes = result_binding.get("bytes")
    if isinstance(declared_bytes, bool) or not isinstance(declared_bytes, int) or declared_bytes <= 0:
        raise ProofConsumerError("result.bytes must be a positive integer")
    stat = _stat(result_path) if verify_result_stat else {
        "bytes": int(result_path.stat().st_size),
        "mtime_ns": int(result_path.stat().st_mtime_ns),
        "mode": int(result_path.stat().st_mode & 0o777),
    }
    if stat["bytes"] != declared_bytes:
        raise ProofConsumerError("result byte stat differs from request")
    if stat["bytes"] > max_result_bytes:
        raise ProofConsumerError("result exceeds execution.max_result_bytes")

    relocation = request.get("relocation")
    if not isinstance(relocation, Mapping):
        raise ProofConsumerError("relocation contract is required")
    roots: list[Path] = []
    for key in ("target_root", "output_root"):
        value = relocation.get(key)
        if not isinstance(value, str):
            raise ProofConsumerError(f"relocation.{key} is required")
        root = Path(value).expanduser().resolve()
        roots.append(root)
    if not any(_under(result_path, root) for root in roots):
        raise ProofConsumerError("result is outside the relocated target/output roots")
    original_roots_value = relocation.get("original_roots")
    if not isinstance(original_roots_value, list) or not original_roots_value:
        raise ProofConsumerError("relocation.original_roots must identify forbidden source roots")
    original_roots = [Path(value).expanduser().resolve() for value in original_roots_value
                      if isinstance(value, str) and value]
    if len(original_roots) != len(original_roots_value):
        raise ProofConsumerError("relocation.original_roots contains a malformed path")
    if any(_under(result_path, root) for root in original_roots):
        raise ProofConsumerError("result path is still under an original source root")

    expected = request.get("expected")
    if not isinstance(expected, Mapping):
        raise ProofConsumerError("expected source/identity/mass/time contract is required")
    source = expected.get("source_binding")
    if not isinstance(source, Mapping):
        raise ProofConsumerError("expected.source_binding is required")
    for key, value in source.items():
        if key == "source_files":
            if not isinstance(value, Mapping) or not value:
                raise ProofConsumerError("expected.source_binding.source_files is empty")
            for role, digest in value.items():
                _sha(digest, f"expected.source_files.{role}")
        elif key.endswith("sha256"):
            _sha(value, f"expected.source_binding.{key}")
    identity = expected.get("case_identity")
    if not isinstance(identity, Mapping) or not identity:
        raise ProofConsumerError("expected.case_identity is required")
    cohort = expected.get("cohort")
    if not isinstance(cohort, Mapping):
        raise ProofConsumerError("expected.cohort is required")
    count = cohort.get("selected_count")
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        raise ProofConsumerError("expected.cohort.selected_count must be a positive integer")
    if cohort.get("identity_key") != "(Zone,Idp)":
        raise ProofConsumerError("identity axis must be (Zone,Idp)")
    _sha(cohort.get("identity_sha256"), "expected.cohort.identity_sha256")
    mass = expected.get("initial_mass_denominator")
    if not isinstance(mass, Mapping):
        raise ProofConsumerError("expected.initial_mass_denominator is required")
    for key in ("denominator_kg", "initial_missing_mass_kg", "later_missing_mass_kg"):
        _finite_nonnegative(mass.get(key), f"expected.initial_mass_denominator.{key}")
    if isinstance(mass.get("later_missing_unique_count"), bool) or not isinstance(mass.get("later_missing_unique_count"), int):
        raise ProofConsumerError("expected later_missing_unique_count must be an integer")
    times = expected.get("time")
    if not isinstance(times, Mapping):
        raise ProofConsumerError("expected.time is required")
    frame_count = times.get("frame_count")
    if isinstance(frame_count, bool) or not isinstance(frame_count, int) or frame_count <= 0:
        raise ProofConsumerError("expected.time.frame_count must be a positive integer")
    for key in ("first_s", "last_s", "tolerance_s"):
        _finite_nonnegative(times.get(key), f"expected.time.{key}")
    if times["last_s"] < times["first_s"]:
        raise ProofConsumerError("expected time interval is reversed")
    profile_sha = times.get("observer_profile_sha256")
    if profile_sha is not None:
        _sha(profile_sha, "expected.time.observer_profile_sha256")
    observer_fields = expected.get("observer_fields", [])
    if not isinstance(observer_fields, list) or any(not isinstance(item, str) for item in observer_fields):
        raise ProofConsumerError("expected.observer_fields must be a list of field names")
    events = expected.get("events")
    if not isinstance(events, Mapping):
        raise ProofConsumerError("expected.events is required")
    required = events.get("status_vocabulary", sorted(FIRST_PASSAGE_STATUSES))
    if not isinstance(required, list) or not set(required).issubset(FIRST_PASSAGE_STATUSES):
        raise ProofConsumerError("expected.events.status_vocabulary contains an unsupported status")
    if events.get("require_unknown_recross") is not True:
        raise ProofConsumerError("unknown recrossing requirement must be explicit")
    if events.get("require_total_net_interval") is not True:
        raise ProofConsumerError("total net interval requirement must be explicit")
    if events.get("require_receiver_labels") is not True:
        raise ProofConsumerError("receiver-label requirement must be explicit")
    guard = request.get("parent_guard_record")
    if guard is not None:
        if not isinstance(guard, Mapping) or not isinstance(guard.get("path"), str):
            raise ProofConsumerError("parent_guard_record.path is malformed")
        guard_path = Path(guard["path"]).expanduser().resolve()
        _sha(guard.get("sha256"), "parent_guard_record.sha256")
        if not guard_path.is_file() or not any(_under(guard_path, root) for root in roots):
            raise ProofConsumerError("parent guard record must be a relocated JSON file")
    return {"result_path": result_path, "result_sha256": expected_result_sha,
            "result_bytes": stat["bytes"], "result_stat": stat,
            "max_wall_seconds": max_wall, "max_result_bytes": max_result_bytes,
            "roots": roots, "original_roots": original_roots,
            "expected": expected, "request": request,
            "parent_guard_record": guard}


def _compare_mapping(actual: Mapping[str, Any], expected: Mapping[str, Any], name: str) -> None:
    for key, value in expected.items():
        if key == "source_files":
            continue
        if actual.get(key) != value:
            raise ProofConsumerError(f"{name}.{key} differs from the bound contract")


def _validate_source_binding(result: Mapping[str, Any], expected: Mapping[str, Any]) -> dict[str, Any]:
    actual = result.get("source_binding")
    if not isinstance(actual, Mapping):
        raise ProofConsumerError("result.source_binding is missing")
    _compare_mapping(actual, expected, "source_binding")
    expected_files = expected.get("source_files")
    actual_files = actual.get("source_files")
    if not isinstance(expected_files, Mapping) or not isinstance(actual_files, Mapping):
        raise ProofConsumerError("source_binding.source_files must be mappings")
    if set(actual_files) != set(expected_files):
        raise ProofConsumerError("source_binding.source_files role set differs")
    for role, digest in expected_files.items():
        if actual_files.get(role) != digest:
            raise ProofConsumerError(f"source_binding.source_files.{role} differs")
    if actual.get("binding_status") not in {None, "EXACT_CURRENT_SOURCE_BOUND", "MANUFACTURED_FIXTURE"}:
        raise ProofConsumerError("source binding status is not a recognized bound/development status")
    return {"current_catalog_sha256": actual.get("current_catalog_sha256"),
            "trajectory_h5_producer_sha256": actual.get("trajectory_h5_producer_sha256"),
            "source_files": dict(actual_files),
            "binding_status": actual.get("binding_status")}


def _validate_time(result: Mapping[str, Any], expected: Mapping[str, Any]) -> dict[str, Any]:
    window = result.get("window")
    if not isinstance(window, Mapping):
        raise ProofConsumerError("result.window is missing")
    frame_count = expected["frame_count"]
    if window.get("frame_count") != frame_count or window.get("frame_start") != 0 or window.get("frame_stop") != frame_count - 1:
        raise ProofConsumerError("result window does not bind the complete expected saved timeline")
    tolerance = _finite_nonnegative(expected["tolerance_s"], "expected.time.tolerance_s")
    first = _compare_float(window.get("time_start_s"), expected["first_s"], "window.time_start_s", tolerance)
    last = _compare_float(window.get("time_stop_s"), expected["last_s"], "window.time_stop_s", tolerance)
    profile = result.get("observer_profile")
    profile_summary: dict[str, Any] = {}
    if profile is not None:
        if not isinstance(profile, Mapping):
            raise ProofConsumerError("observer_profile must be an object")
        expected_profile_sha = expected.get("observer_profile_sha256")
        if expected_profile_sha is not None and profile.get("sha256") != expected_profile_sha:
            raise ProofConsumerError("observer profile SHA differs")
        query_times = profile.get("query_times_s")
        if query_times is None or not isinstance(query_times, list) or not query_times:
            raise ProofConsumerError("observer profile query_times_s is missing")
        parsed = [_finite(value, "observer_profile.query_times_s") for value in query_times]
        if any(right <= left for left, right in zip(parsed, parsed[1:])):
            raise ProofConsumerError("observer profile query times are not strictly increasing")
        if parsed[0] < first - tolerance or parsed[-1] > last + tolerance:
            raise ProofConsumerError("observer profile query times lie outside the saved window")
        profile_summary = {"sha256": profile.get("sha256"),
                           "query_count": len(parsed), "query_first_s": parsed[0],
                           "query_last_s": parsed[-1],
                           "observable_names": list(profile.get("observable_names", []))}
    observations = result.get("frame_observations")
    if expected.get("observer_fields") and observations is None:
        raise ProofConsumerError("required observer fields need frame_observations")
    if observations is not None:
        if not isinstance(observations, list) or len(observations) != frame_count:
            raise ProofConsumerError("frame_observations shape differs from the saved timeline")
        observed_times: list[float] = []
        for index, item in enumerate(observations):
            if not isinstance(item, Mapping):
                raise ProofConsumerError(f"frame_observations[{index}] is malformed")
            observed_times.append(_finite(item.get("time_s"), f"frame_observations[{index}].time_s"))
            quality = item.get("quality")
            if quality is not None:
                _unknown_quality(quality, f"frame_observations[{index}].quality")
            for field in expected.get("observer_fields", []):
                if field not in item:
                    raise ProofConsumerError(f"frame_observations[{index}] lacks required observer field {field}")
            if "mass_weighted_com_m" in expected.get("observer_fields", []):
                com = item.get("mass_weighted_com_m")
                if not isinstance(com, list) or len(com) != 3:
                    raise ProofConsumerError(f"frame_observations[{index}].mass_weighted_com_m must be a 3-vector in metres")
                [_finite(value, "mass_weighted_com_m") for value in com]
            if "mass_weighted_mean_velocity_m_s" in expected.get("observer_fields", []):
                velocity = item.get("mass_weighted_mean_velocity_m_s")
                if velocity is not None:
                    if not isinstance(velocity, list) or len(velocity) != 3:
                        raise ProofConsumerError(f"frame_observations[{index}].mass_weighted_mean_velocity_m_s must be a 3-vector or null")
                    [_finite(value, "mass_weighted_mean_velocity_m_s") for value in velocity]
                elif not str(item.get("velocity_observation_status", "")).startswith(("PARTIAL_", "UNKNOWN_")):
                    raise ProofConsumerError(f"frame_observations[{index}] has null velocity without an explicit missing/unknown status")
            if "mass_weighted_kinetic_energy_J" in expected.get("observer_fields", []):
                kinetic_energy = item.get("mass_weighted_kinetic_energy_J")
                if kinetic_energy is None:
                    if not str(item.get("velocity_observation_status", "")).startswith(("PARTIAL_", "UNKNOWN_")):
                        raise ProofConsumerError(f"frame_observations[{index}] has null kinetic energy without an explicit missing/unknown status")
                else:
                    _finite_nonnegative(kinetic_energy,
                                        f"frame_observations[{index}].mass_weighted_kinetic_energy_J")
            if "mass_quantile_front_m" in expected.get("observer_fields", []):
                fronts = item.get("mass_quantile_front_m")
                if not isinstance(fronts, list) or not fronts:
                    raise ProofConsumerError(f"frame_observations[{index}].mass_quantile_front_m is missing")
                [_finite(value, "mass_quantile_front_m") for value in fronts]
        if any(right <= left for left, right in zip(observed_times, observed_times[1:])):
            raise ProofConsumerError("frame observation times are not strictly increasing")
        if abs(observed_times[0] - first) > tolerance or abs(observed_times[-1] - last) > tolerance:
            raise ProofConsumerError("frame observation endpoints differ from window")
    required_names = list(expected.get("observer_fields", []))
    if required_names and profile_summary:
        missing_names = sorted(set(required_names) - set(profile_summary.get("observable_names", [])))
        if missing_names:
            raise ProofConsumerError(f"observer profile omits required fields: {missing_names}")
    return {"frame_count": frame_count, "first_s": first, "last_s": last,
            "profile": profile_summary,
            "frame_observations_present": observations is not None,
            "observer_fields": required_names,
            "units": {
                "time": "s", "initial_mass": "kg", "position": "m",
                "velocity": "m/s (world inertial)", "kinetic_energy": "J",
                "mass_time": "kg*s", "net_flux": "kg",
            }}


def _validate_label(label: Mapping[str, Any], index: int, first: float, last: float,
                    tolerance: float) -> tuple[str, bool]:
    status = label.get("status")
    if status not in FIRST_PASSAGE_STATUSES:
        raise ProofConsumerError(f"labels[{index}].status is unsupported: {status!r}")
    mass = _finite_nonnegative(label.get("initial_mass_kg"), f"labels[{index}].initial_mass_kg")
    if mass <= 0:
        raise ProofConsumerError(f"labels[{index}].initial_mass_kg must be positive")
    bracket = label.get("first_saved_bracket_s")
    if bracket is not None:
        if not isinstance(bracket, list) or len(bracket) != 2:
            raise ProofConsumerError(f"labels[{index}].first_saved_bracket_s is malformed")
        left = _finite(bracket[0], f"labels[{index}] bracket left")
        right = _finite(bracket[1], f"labels[{index}] bracket right")
        if not (left < right and left >= first - tolerance and right <= last + tolerance):
            raise ProofConsumerError(f"labels[{index}] first saved bracket is outside the timeline")
    if status in {"observed", "ambiguous_multiple_crossing"} and bracket is None:
        raise ProofConsumerError(f"labels[{index}] event status lacks its first saved bracket")
    event_time = label.get("event_time_s")
    if status == "observed":
        event_value = _finite(event_time, f"labels[{index}].event_time_s")
        if bracket is None or not (bracket[0] - tolerance <= event_value <= bracket[1] + tolerance):
            raise ProofConsumerError(f"labels[{index}] observed event is outside its first bracket")
        candidates = label.get("crossing_candidate_times_s")
        if not isinstance(candidates, list) or not candidates:
            raise ProofConsumerError(f"labels[{index}] observed event lacks crossing candidates")
        candidate_values = [_finite(value, f"labels[{index}] crossing candidate") for value in candidates]
        if any(right < left for left, right in zip(candidate_values, candidate_values[1:])):
            raise ProofConsumerError(f"labels[{index}] crossing candidates are not sorted")
        if abs(candidate_values[0] - event_value) > tolerance:
            raise ProofConsumerError(f"labels[{index}] event time is not its first candidate")
    elif event_time is not None:
        raise ProofConsumerError(f"labels[{index}] non-observed status has an event time")
    if status == "ambiguous_multiple_crossing":
        candidates = label.get("crossing_candidate_times_s")
        if not isinstance(candidates, list) or len(candidates) < 2:
            raise ProofConsumerError(f"labels[{index}] ambiguity lacks explicit candidates")
        if bracket is None or not all(bracket[0] - tolerance <= _finite(value, "ambiguous candidate") <= bracket[1] + tolerance for value in candidates):
            raise ProofConsumerError(f"labels[{index}] ambiguous candidates are not in the first saved bracket")
    recross = label.get("recross_status")
    if not isinstance(recross, str) or "UNKNOWN" not in recross.upper():
        raise ProofConsumerError(f"labels[{index}] does not preserve unknown recrossing semantics")
    speed = label.get("relative_normal_speed_m_s")
    velocity_status = label.get("velocity_status")
    if speed is not None:
        _finite(speed, f"labels[{index}].relative_normal_speed_m_s")
        if velocity_status == "UNKNOWN_VELOCITY":
            raise ProofConsumerError(f"labels[{index}] exposes a speed while velocity is UNKNOWN")
    return str(status), speed is not None


def _validate_receiver_label(label: Mapping[str, Any], index: int, first: float, last: float,
                             tolerance: float) -> str:
    status = label.get("status")
    if status not in RECEIVER_STATUSES:
        raise ProofConsumerError(f"receiver_volume_labels[{index}] status is unsupported")
    destination = label.get("final_destination_status")
    if destination not in DESTINATION_STATUSES:
        raise ProofConsumerError(f"receiver_volume_labels[{index}] destination is unsupported")
    bracket = label.get("first_saved_bracket_s")
    if bracket is not None:
        if not isinstance(bracket, list) or len(bracket) != 2:
            raise ProofConsumerError(f"receiver_volume_labels[{index}] bracket is malformed")
        values = [_finite(value, "receiver bracket") for value in bracket]
        if not (values[0] < values[1] and values[0] >= first - tolerance and values[1] <= last + tolerance):
            raise ProofConsumerError(f"receiver_volume_labels[{index}] bracket is outside timeline")
    if status in {"observed", "ambiguous_multiple_crossing"} and bracket is None:
        raise ProofConsumerError(f"receiver_volume_labels[{index}] event lacks first bracket")
    aperture_status = label.get("aperture_first_arrival_status")
    if aperture_status is None:
        raise ProofConsumerError(f"receiver_volume_labels[{index}] aperture status is missing")
    if not isinstance(aperture_status, str):
        raise ProofConsumerError(f"receiver_volume_labels[{index}] aperture status is malformed")
    return str(status)


def _validate_events(result: Mapping[str, Any], expected: Mapping[str, Any],
                     *, first: float, last: float, tolerance: float) -> dict[str, Any]:
    labels = result.get("labels")
    if not isinstance(labels, list) or not labels:
        raise ProofConsumerError("result.labels is missing")
    counts: Counter[str] = Counter()
    speed_observed = 0
    for index, label in enumerate(labels):
        status, has_speed = _validate_label(label, index, first, last, tolerance)
        counts[status] += 1
        speed_observed += int(has_speed)
    summary = result.get("event_summary")
    if not isinstance(summary, Mapping):
        raise ProofConsumerError("result.event_summary is missing")
    declared = summary.get("label_counts")
    if declared is not None and declared != dict(counts):
        raise ProofConsumerError("event_summary.label_counts differs from particle labels")
    receiver_labels = result.get("receiver_volume_labels")
    if expected.get("require_receiver_labels") is True:
        if not isinstance(receiver_labels, list) or len(receiver_labels) != len(labels):
            raise ProofConsumerError("receiver_volume_labels are missing or have the wrong shape")
        receiver_counts: Counter[str] = Counter()
        for index, (label, receiver) in enumerate(zip(labels, receiver_labels)):
            if not isinstance(receiver, Mapping):
                raise ProofConsumerError(f"receiver_volume_labels[{index}] is malformed")
            if (receiver.get("zone"), receiver.get("idp")) != (label.get("zone"), label.get("idp")):
                raise ProofConsumerError(f"receiver label identity differs at index {index}")
            receiver_counts[_validate_receiver_label(receiver, index, first, last, tolerance)] += 1
        declared_receiver = summary.get("receiver_volume_label_counts")
        if declared_receiver is not None and declared_receiver != dict(receiver_counts):
            raise ProofConsumerError("event_summary.receiver_volume_label_counts differs")
    else:
        receiver_counts = Counter()

    for legacy in ("net_flux_interval_kg", "net_flux_mass_kg", "net_flux_unknown_interval_kg"):
        if legacy in summary:
            raise ProofConsumerError(f"legacy ambiguous flux field remains: {legacy}")
    total_interval = summary.get("net_flux_total_interval_kg")
    if not isinstance(total_interval, list) or len(total_interval) != 2:
        raise ProofConsumerError("corrected total net flux interval is missing")
    lower = _finite(total_interval[0], "net_flux_total_interval_kg.lower")
    upper = _finite(total_interval[1], "net_flux_total_interval_kg.upper")
    if lower > upper:
        raise ProofConsumerError("net flux interval is reversed")
    gross_status = summary.get("gross_flux_status")
    if summary.get("gross_flux_mass_kg") is not None or not isinstance(gross_status, str) or "UNKNOWN" not in gross_status.upper():
        raise ProofConsumerError("gross hidden recrossing must remain UNKNOWN")
    unknown_contribution = summary.get("net_flux_unknown_endpoint_contribution_interval_kg")
    known_subtotal = summary.get("net_flux_known_endpoint_subtotal_kg")
    if unknown_contribution is not None or known_subtotal is not None:
        if not isinstance(unknown_contribution, list) or len(unknown_contribution) != 2:
            raise ProofConsumerError("unknown endpoint contribution interval is missing")
        unknown_low = _finite(unknown_contribution[0], "unknown endpoint lower")
        unknown_high = _finite(unknown_contribution[1], "unknown endpoint upper")
        known_value = _finite(known_subtotal, "known endpoint subtotal")
        if unknown_low < 0 or unknown_high < unknown_low or not math.isclose(lower, known_value, abs_tol=1e-9) or not math.isclose(upper, known_value + unknown_high, abs_tol=1e-9):
            raise ProofConsumerError("total net interval is not the known subtotal plus unknown contribution")
    residence_mode = summary.get("residence_output_mode")
    if residence_mode is not None and "per_particle_compact" not in str(residence_mode):
        raise ProofConsumerError("residence output is not identity-preserving compact output")
    unknown_residence = summary.get("residence_unknown_mass_time_semantics")
    if unknown_residence is not None and "upper" not in str(unknown_residence).lower():
        raise ProofConsumerError("unknown residence mass-time is not retained as an upper-bound interval")
    if expected.get("require_residence_semantics") is True:
        if "per_particle_compact" not in str(residence_mode):
            raise ProofConsumerError("per-particle residence output is required")
        if unknown_residence is None or "upper" not in str(unknown_residence).lower():
            raise ProofConsumerError("residence unknown interval semantics are required")
        _finite_nonnegative(summary.get("residence_known_mass_time_kg_s"),
                            "event_summary.residence_known_mass_time_kg_s")
        unknown_mass_time = summary.get("residence_unknown_mass_time_kg_s")
        if unknown_mass_time is not None:
            _finite_nonnegative(unknown_mass_time, "event_summary.residence_unknown_mass_time_kg_s")
    return {"label_status_counts": dict(counts),
            "receiver_status_counts": dict(receiver_counts),
            "labels_count": len(labels),
            "speed_observed_count": speed_observed,
            "required_status_vocabulary": list(expected.get("status_vocabulary", sorted(FIRST_PASSAGE_STATUSES))),
            "status_vocabulary_missing_in_this_case": sorted(set(expected.get("status_vocabulary", FIRST_PASSAGE_STATUSES)) - set(counts)),
            "unknown_recrossings": "EXPLICIT_PER_LABEL_UNKNOWN_REQUIRED",
            "first_saved_brackets_preserved": True,
            "net_flux_total_interval_kg": [lower, upper],
            "gross_flux_status": gross_status,
            "residence_scope": residence_mode or "NOT_DECLARED"}


def _validate_result(result: Mapping[str, Any], bound: Mapping[str, Any],
                     result_sha: str, result_bytes: int) -> dict[str, Any]:
    if result.get("schema") != RESULT_SCHEMA:
        raise ProofConsumerError("fresh result schema is not V16")
    if result_sha in OLD_PROOF_SHA256:
        raise ProofConsumerError("fresh result SHA is the forbidden historical proof SHA")
    if result.get("model_invoked") is not False or result.get("cfd_invoked") is True:
        raise ProofConsumerError("result model/CFD flags are not closed")
    _unknown_quality(result.get("quality"), "result quality")
    expected = bound["expected"]
    expected_observer_fields = expected.get("observer_fields", [])
    if expected_observer_fields:
        velocity_semantics = result.get("velocity_semantics")
        if not isinstance(velocity_semantics, str) or "world_inertial" not in velocity_semantics:
            raise ProofConsumerError("result velocity semantics do not preserve world-inertial units")
    source_summary = _validate_source_binding(result, expected["source_binding"])
    identity = result.get("case_identity")
    if not isinstance(identity, Mapping):
        raise ProofConsumerError("result.case_identity is missing")
    _compare_mapping(identity, expected["case_identity"], "case_identity")
    cohort = result.get("cohort")
    if not isinstance(cohort, Mapping):
        raise ProofConsumerError("result.cohort is missing")
    expected_cohort = expected["cohort"]
    selected_count = cohort.get("selected_count", cohort.get("expected_initial_fluid_count"))
    if selected_count != expected_cohort["selected_count"]:
        raise ProofConsumerError("result cohort selected_count differs")
    if cohort.get("identity_key") != expected_cohort["identity_key"]:
        raise ProofConsumerError("result cohort identity_key differs")
    labels = result.get("labels")
    if not isinstance(labels, list) or len(labels) != expected_cohort["selected_count"]:
        raise ProofConsumerError("result labels count differs from the bound cohort")
    pairs = [(int(item.get("zone")), int(item.get("idp"))) for item in labels if isinstance(item, Mapping)]
    if len(pairs) != len(labels) or pairs != sorted(pairs):
        raise ProofConsumerError("labels are not sorted on the bound (Zone,Idp) axis")
    identity_sha = _identity_sha(labels)
    if identity_sha != expected_cohort["identity_sha256"]:
        raise ProofConsumerError("label identity SHA differs from the bound CURRENT cohort")
    for key in ("selected_identity_sha256", "source_identity_set_sha256"):
        if key in cohort and cohort.get(key) != identity_sha:
            raise ProofConsumerError(f"result cohort {key} differs from label identity SHA")
    mass = result.get("initial_mass_denominator")
    if not isinstance(mass, Mapping):
        raise ProofConsumerError("result.initial_mass_denominator is missing")
    expected_mass = expected["initial_mass_denominator"]
    mass_tolerance = _finite_nonnegative(expected_mass.get("tolerance_kg", 5e-8), "mass tolerance")
    denominator = _compare_float(mass.get("denominator_kg"), expected_mass["denominator_kg"], "denominator_kg", mass_tolerance)
    initial_missing = _compare_float(mass.get("initial_missing_mass_kg"), expected_mass["initial_missing_mass_kg"], "initial_missing_mass_kg", mass_tolerance)
    later_missing = _compare_float(mass.get("later_missing_mass_kg"), expected_mass["later_missing_mass_kg"], "later_missing_mass_kg", mass_tolerance)
    if mass.get("later_missing_unique_count") != expected_mass["later_missing_unique_count"]:
        raise ProofConsumerError("later missing identity count differs")
    if not math.isclose(denominator, initial_missing + _finite(mass.get("initial_fluid_mass_kg", denominator - initial_missing), "initial_fluid_mass_kg"), abs_tol=mass_tolerance):
        raise ProofConsumerError("initial mass denominator is not initial fluid plus initial missing mass")
    if not math.isclose(sum(_finite(item.get("initial_mass_kg"), "label initial mass") for item in labels), denominator, abs_tol=mass_tolerance):
        raise ProofConsumerError("label initial masses do not sum to the frozen denominator")
    if "missing_scope" in mass and "denominator" not in str(mass["missing_scope"]).lower():
        raise ProofConsumerError("mass missing_scope does not state denominator semantics")
    time_summary = _validate_time(result, expected["time"])
    events = _validate_events(result, expected["events"], first=time_summary["first_s"], last=time_summary["last_s"], tolerance=_finite_nonnegative(expected["time"]["tolerance_s"], "time tolerance"))
    return {"source_binding": source_summary,
            "case_identity": dict(identity),
            "cohort": {"selected_count": len(labels), "identity_key": "(Zone,Idp)", "identity_sha256": identity_sha},
            "initial_mass_denominator": {"denominator_kg": denominator,
                                          "initial_missing_mass_kg": initial_missing,
                                          "later_missing_mass_kg": later_missing,
                                          "later_missing_unique_count": mass["later_missing_unique_count"],
                                          "denominator_unchanged_by_later_missing": True},
            "time": time_summary, "events": events, "result_bytes": result_bytes,
            "result_sha256": result_sha}


def _guard_record(bound: Mapping[str, Any], parent_pid: int | None) -> dict[str, Any]:
    guard = bound.get("parent_guard_record")
    if guard is None:
        return {"supplied": False, "ancestry_credit": "NOT_CLAIMED; outer V4 guard must supply actual process ancestry"}
    path = Path(str(guard["path"])).expanduser().resolve()
    actual_sha, bytes_read = sha256_file(path)
    if actual_sha != guard["sha256"]:
        raise ProofConsumerError("parent guard record SHA differs")
    record = _load_object(path)
    if parent_pid is not None:
        recorded = record.get("root_pid", record.get("parent_pid", record.get("supervisor_pid")))
        if recorded is not None and int(recorded) != int(parent_pid):
            raise ProofConsumerError("guard record PID does not equal the direct parent")
    if record.get("ancestry_status") in {"UNKNOWN", "UNRESOLVED"}:
        raise ProofConsumerError("guard ancestry is unresolved; no portable credit")
    return {"supplied": True, "path": str(path), "sha256": actual_sha,
            "bytes": path.stat().st_size, "bytes_read": bytes_read,
            "ancestry_status": record.get("ancestry_status", "RECORDED_BY_PARENT_GUARD"),
            "credit": "parent guard record consumed; this worker does not invent PID lists"}


def preflight(request_path: Path | str) -> dict[str, Any]:
    request_file = Path(request_path).expanduser().resolve()
    request = _load_object(request_file)
    bound = _validate_request(request, verify_result_stat=True)
    return {"schema": PROOF_SCHEMA, "status": "READY_FOR_PARENT_IO_SLOT",
            "metadata_only": True, "request": {"path": str(request_file), "sha256": sha256_file(request_file)[0]},
            "result": {"path": str(bound["result_path"]), "bytes": bound["result_bytes"],
                       "sha256_declared": bound["result_sha256"], "content_sha_verified": False},
            "json_only": True, "hdf5_or_bi4_content_read": False,
            "raw_opened": False, "model_invoked": False, "cfd_invoked": False,
            "ledger_mutated": False, "qualification": dict(UNKNOWN)}


def run(request_path: Path | str, output_path: Path | str, *, io_slot_approved: bool = False,
        parent_pid: int | None = None, max_wall_seconds: float | None = None) -> dict[str, Any]:
    entry_wall = time.monotonic()
    entry_resource = _resource_snapshot()
    request_file = Path(request_path).expanduser().resolve()
    previous: Any | None = None
    if io_slot_approved:
        if parent_pid is None or int(parent_pid) <= 1:
            raise ProofConsumerError("--parent-pid is required for an approved JSON-only run")
        if max_wall_seconds is None:
            raise ProofConsumerError("--max-wall-seconds is required for an approved JSON-only run")
        # The parent/deadline guard starts before request validation.  The
        # request is small, but charging its validation outside the guard
        # would make the scope ambiguous and would repeat the old parent
        # prevalidation bug.
        previous = _begin_timer(float(max_wall_seconds))
    try:
        if io_slot_approved:
            _pdeathsig(int(parent_pid))
        request = _load_object(request_file)
        bound = _validate_request(request, verify_result_stat=True)
        if max_wall_seconds is not None and abs(float(max_wall_seconds) - bound["max_wall_seconds"]) > 1e-9:
            raise ProofConsumerError("CLI max wall differs from the request")
        if not io_slot_approved:
            return preflight(request_file)
        result, observed_sha, result_bytes = _read_result(bound["result_path"], bound["max_result_bytes"])
        if observed_sha != bound["result_sha256"]:
            raise ProofConsumerError("fresh V16 result SHA differs from the request")
        paths = _path_audit(result, original_roots=bound["original_roots"], allowed_roots=bound["roots"])
        if paths["actionable_original_path_hits"]:
            raise ProofConsumerError("result contains an actionable original-source path")
        if paths["unbound_absolute_paths"]:
            raise ProofConsumerError("result contains an unbound absolute path")
        summary = _validate_result(result, bound, observed_sha, result_bytes)
        guard_summary = _guard_record(bound, int(parent_pid))
        output = Path(output_path).expanduser().resolve()
        if output.exists():
            raise ProofConsumerError(f"refusing to overwrite proof output: {output}")
        if not any(_under(output, root) for root in bound["roots"]):
            raise ProofConsumerError("proof output is outside relocated roots")
        output.parent.mkdir(parents=True, exist_ok=True)
        elapsed = time.monotonic() - entry_wall
        usage = _resource_snapshot()
        proof: dict[str, Any] = {
            "schema": PROOF_SCHEMA,
            "status": "FRESH_V16_RESULT_VERIFIED_DEVELOPMENT_UNKNOWN",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "request": {"path": str(request_file), "sha256": sha256_file(request_file)[0]},
            "source_result": {"path": str(bound["result_path"]), "sha256": observed_sha,
                              "bytes": result_bytes, "stat": bound["result_stat"],
                              "content_sha_verified": True,
                              "historical_proof_sha_rejected": sorted(OLD_PROOF_SHA256)},
            "parent_guard": guard_summary,
            "execution": {"json_only": True, "hdf5_or_bi4_content_read": False,
                          "raw_opened": False, "model_invoked": False, "cfd_invoked": False,
                          "ledger_mutated": False, "parent_pid": int(parent_pid),
                          "direct_parent_verified": True, "elapsed_wall_seconds": elapsed,
                          "resource_at_entry": entry_resource, "resource_at_exit": usage,
                          "result_bytes_read": result_bytes,
                          "source_path_audit": paths},
            "source_binding": summary["source_binding"],
            "case_identity": summary["case_identity"],
            "cohort": summary["cohort"],
            "initial_mass_denominator": summary["initial_mass_denominator"],
            "time": summary["time"], "event_censor": summary["events"],
            "quality": dict(UNKNOWN), "qualification": dict(UNKNOWN),
            "credit_boundary": (
                "Independent JSON result binding only. This proof grants no QI/QN/QE, "
                "does not validate HDF5/BI4 reconstruction, and preserves all "
                "censoring, hidden recrossing, and physical-fate UNKNOWN states."
            ),
        }
        proof["sha256"] = canonical_sha(proof)
        with output.open("x", encoding="utf-8") as stream:
            json.dump(proof, stream, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
        return {"schema": PROOF_SCHEMA, "status": proof["status"],
                "proof_path": str(output), "proof_sha256": proof["sha256"],
                "result_sha256": observed_sha, "result_bytes": result_bytes,
                "hdf5_or_bi4_content_read": False, "model_invoked": False,
                "cfd_invoked": False, "ledger_mutated": False,
                "qualification": dict(UNKNOWN)}
    finally:
        _end_timer(previous)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("preflight")
    prep.add_argument("--request", type=Path, required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    run_parser.add_argument("--io-slot-approved", action="store_true")
    run_parser.add_argument("--parent-pid", type=int)
    run_parser.add_argument("--max-wall-seconds", type=float)
    args = parser.parse_args(argv)
    try:
        if args.command == "preflight":
            value = preflight(args.request)
        else:
            value = run(args.request, args.output, io_slot_approved=args.io_slot_approved,
                        parent_pid=args.parent_pid, max_wall_seconds=args.max_wall_seconds)
    except (ProofConsumerError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"fresh V16 proof consumer v8: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
