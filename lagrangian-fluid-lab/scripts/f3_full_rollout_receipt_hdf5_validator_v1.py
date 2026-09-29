#!/usr/bin/env python3
"""Read-only validator for an F3 rollout receipt and its trajectory HDF5.

The validator is intentionally a sidecar.  It does not import the learning
runner, open a dataset manifest, start a worker, or write a receipt.  The
only files it opens are the supplied evaluation JSON (text read) and the
supplied trajectory HDF5 (``h5py.File(..., "r")``).

The checked contract mirrors the public ``core.evaluation.v1`` rollout shape:

* a complete F3 rollout has 835 transitions and 836 saved states;
* a bounded ``maximum_steps`` rollout keeps the registered 835-transition
  denominator in JSON but stores only ``maximum_steps + 1`` HDF5 states;
* JSON completion/failure flags and metric prefixes agree with one another;
* the trajectory is bound through a read-only, single-link descriptor with
  stable fd/stat/size/hash identity and parsed only from an immutable byte
  snapshot; external/soft links and virtual datasets are rejected before any
  dataset is dereferenced; and
* HDF5 identity, shape, time, validity, finite-state, and tail semantics are
  internally consistent; and
* ``future_state_inputs`` is explicitly false in both artifacts.

``validate_receipt`` raises :class:`ValidationError` on every mismatch.
``run_validation`` converts the same error into a structured fail-closed
result for command-line use.  Neither entry point mutates its inputs.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from numbers import Integral, Real
import os
from pathlib import Path
import stat
import sys
from typing import Any, Mapping

if __name__ == "__main__":
    # A read-only command should not leave __pycache__ files beside the new
    # sidecar when it is invoked directly from a repository checkout.
    sys.dont_write_bytecode = True

import h5py
import numpy as np


SCHEMA = "core.f3.full_rollout_receipt_hdf5_validation.v1"
EVALUATION_SCHEMA = "core.evaluation.v1"
DEFAULT_EXPECTED_TRANSITIONS = 835
# The current-manifest 835-step/34,560-particle trajectory observed on
# 2026-09-29 is 723,147,992 bytes.  A one-GiB file budget covers that exact
# artifact with finite headroom while keeping each of the two stable reads
# bounded (the two returned raw snapshots total at most two GiB; the 1-MiB
# chunk assembly adds only a separately bounded transient overhead).
# This is deliberately a file-size cap, not an unbounded allowance: the
# single-link, immutable-snapshot, HDF5-link, shape, finite-state, tail, and
# future-state checks below remain mandatory.
MAX_HDF5_BYTES = 1 * 1024 * 1024 * 1024
MAX_HDF5_LINKS = 8192
REQUIRED_DATASETS = frozenset(
    {"time", "position", "velocity", "particle_id", "particle_zone", "mass", "valid"}
)


class ValidationError(ValueError):
    """A receipt/HDF5 mismatch that must not be interpreted as a pass."""


def _fail(message: str) -> None:
    raise ValidationError(f"fail-closed: {message}")


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{name} must be an object")
    return value


def _strict_bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        _fail(f"{name} must be a boolean")
    return value


def _strict_int(value: Any, name: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        _fail(f"{name} must be an integer")
    result = int(value)
    if minimum is not None and result < minimum:
        _fail(f"{name} must be >= {minimum}")
    return result


def _strict_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        _fail(f"{name} must be numeric")
    result = float(value)
    if not np.isfinite(result):
        _fail(f"{name} must be finite")
    return result


def _strict_false(value: Any, name: str) -> None:
    """Accept HDF5's scalar bool/integer representation, never strings."""
    if isinstance(value, (bool, np.bool_)):
        if bool(value):
            _fail(f"{name} must be false")
        return
    if isinstance(value, Integral) and not isinstance(value, bool):
        if int(value) != 0:
            _fail(f"{name} must be false")
        return
    _fail(f"{name} must be an explicit false boolean")


def _strict_true(value: Any, name: str) -> None:
    if isinstance(value, (bool, np.bool_)):
        if not bool(value):
            _fail(f"{name} must be true")
        return
    if isinstance(value, Integral) and not isinstance(value, bool):
        if int(value) != 1:
            _fail(f"{name} must be true")
        return
    _fail(f"{name} must be an explicit true boolean")


def _finite_metric_prefix(values: Any, *, name: str, expected: int, executed: int) -> None:
    if not isinstance(values, list) or len(values) != expected:
        _fail(f"{name} must have the fixed {expected}-frame denominator")
    for index, value in enumerate(values):
        if index < executed:
            _strict_number(value, f"{name}[{index}]")
        elif value is not None:
            _fail(f"{name}[{index}] must be null after the executed prefix")


def _resolve_path(value: Any, *, base: Path, name: str) -> Path:
    if not isinstance(value, (str, Path)) or not value:
        _fail(f"{name} must be a non-empty path")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    raw = os.fspath(path)
    if "\x00" in raw:
        _fail(f"{name} contains a NUL byte")
    # Do not call Path.resolve() here: resolving a symlink before the secure
    # open would erase the very path identity that the HDF5 boundary must
    # reject.  The secure reader below performs the existence check from an
    # O_NOFOLLOW directory-fd walk.
    return Path(os.path.abspath(raw))


def _load_evaluation(path: Path) -> dict[str, Any]:
    if not path.is_file():
        _fail(f"evaluation JSON does not exist: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        _fail(f"evaluation JSON cannot be read: {error}")
    return dict(_mapping(value, "evaluation JSON"))


def _select_case(evaluation: Mapping[str, Any], requested_case_id: str | None) -> tuple[str, Mapping[str, Any]]:
    cases = _mapping(evaluation.get("cases"), "evaluation.cases")
    if not cases:
        _fail("evaluation.cases must not be empty")
    if requested_case_id is None:
        if len(cases) != 1:
            _fail("case_id is required when evaluation contains multiple cases")
        case_id = next(iter(cases))
    else:
        if not isinstance(requested_case_id, str) or not requested_case_id:
            _fail("case_id must be a non-empty string")
        case_id = requested_case_id
    if case_id not in cases:
        _fail(f"case_id is not present in evaluation.cases: {case_id}")
    return case_id, _mapping(cases[case_id], f"evaluation.cases[{case_id!r}]")


def _validate_case_lists(evaluation: Mapping[str, Any], case_id: str) -> None:
    for name in ("registered_case_ids", "selected_case_ids"):
        values = evaluation.get(name)
        if not isinstance(values, list) or not values or any(
                not isinstance(item, str) or not item for item in values):
            _fail(f"evaluation.{name} must be a non-empty string list")
        if len(set(values)) != len(values):
            _fail(f"evaluation.{name} contains duplicate case IDs")
        if case_id not in values:
            _fail(f"evaluation.{name} does not contain selected case {case_id!r}")


def _validate_score(row: Mapping[str, Any], *, expected: int, executed: int,
                    failure_category: str | None, execution_complete: bool) -> None:
    score = _mapping(row.get("score"), "case.score")
    score_expected = _strict_int(score.get("expected_frames"), "case.score.expected_frames",
                                 minimum=1)
    if score_expected != expected:
        _fail("case.score.expected_frames disagrees with the fixed denominator")
    finite_prefix = _strict_int(score.get("finite_prefix_frames"),
                                "case.score.finite_prefix_frames", minimum=0)
    if finite_prefix != executed:
        _fail("case.score.finite_prefix_frames disagrees with the executed prefix")
    if _strict_bool(score.get("executed"), "case.score.executed") is not _strict_bool(
            row.get("executed"), "case.executed"):
        _fail("case.score.executed disagrees with case.executed")
    if _strict_bool(score.get("complete"), "case.score.complete") is not execution_complete:
        _fail("case.score.complete disagrees with rollout completion")
    score_failure = score.get("failure_category")
    if score_failure != failure_category:
        _fail("case.score.failure_category disagrees with case.failure_category")
    if "raw_error_coverage" in score:
        coverage = _strict_number(score["raw_error_coverage"], "case.score.raw_error_coverage")
        expected_coverage = executed / expected
        if not np.isclose(coverage, expected_coverage, rtol=0.0, atol=1.0e-12):
            _fail("case.score.raw_error_coverage disagrees with the executed prefix")


def _validate_evaluation(path: Path, requested_case_id: str | None,
                         expected_transitions: int) -> tuple[dict[str, Any], str,
                                                              Mapping[str, Any], Path]:
    evaluation = _load_evaluation(path)
    if evaluation.get("schema") != EVALUATION_SCHEMA:
        _fail("unsupported evaluation schema")
    if "autonomous" in evaluation:
        if _strict_bool(evaluation["autonomous"], "evaluation.autonomous") is not True:
            _fail("evaluation.autonomous must be true")
    else:
        _fail("evaluation.autonomous is missing")
    _strict_false(evaluation.get("future_state_inputs"), "evaluation.future_state_inputs")

    mode = evaluation.get("evaluation_mode")
    if mode not in {"diagnostic", "formal"}:
        _fail("evaluation.evaluation_mode is invalid")
    if "diagnostic" in evaluation and _strict_bool(
            evaluation["diagnostic"], "evaluation.diagnostic") is not (mode == "diagnostic"):
        _fail("evaluation.diagnostic disagrees with evaluation_mode")
    if "formal_eligible" in evaluation and _strict_bool(
            evaluation["formal_eligible"], "evaluation.formal_eligible") is not (mode == "formal"):
        _fail("evaluation.formal_eligible disagrees with evaluation_mode")

    maximum_steps = evaluation.get("maximum_steps")
    if maximum_steps is not None:
        maximum_steps = _strict_int(maximum_steps, "evaluation.maximum_steps", minimum=1)
    case_id, row = _select_case(evaluation, requested_case_id)
    _validate_case_lists(evaluation, case_id)

    expected_map = _mapping(evaluation.get("expected_frames"), "evaluation.expected_frames")
    expected = _strict_int(expected_map.get(case_id),
                           f"evaluation.expected_frames[{case_id!r}]", minimum=1)
    if expected != expected_transitions:
        _fail(f"expected transition count must be {expected_transitions}, got {expected}")

    row_case_id = row.get("case_id")
    if row_case_id != case_id:
        _fail("case.case_id disagrees with the selected case")
    for name in ("frames_expected", "expected_frames"):
        value = _strict_int(row.get(name), f"case.{name}", minimum=1)
        if value != expected:
            _fail(f"case.{name} disagrees with the fixed denominator")
    executed = _strict_int(row.get("frames_executed"), "case.frames_executed", minimum=0)
    predicted = _strict_int(row.get("frames_predicted"), "case.frames_predicted", minimum=0)
    if executed > expected or predicted != executed:
        _fail("case frame counts are inconsistent")

    executed_flag = _strict_bool(row.get("executed"), "case.executed")
    if not executed_flag and executed != 0:
        _fail("case.executed=false cannot have executed frames")
    failure_category = row.get("failure_category")
    if failure_category is not None and (
            not isinstance(failure_category, str) or not failure_category):
        _fail("case.failure_category must be null or a non-empty string")
    first_failure = row.get("first_failure_frame")
    if failure_category is None:
        if first_failure is not None:
            _fail("case.first_failure_frame must be null for a complete attempt")
    else:
        first_failure = _strict_int(first_failure, "case.first_failure_frame", minimum=1)
        if first_failure != executed + 1:
            _fail("case.first_failure_frame must follow the executed prefix")

    execution_complete = bool(expected > 0 and executed == expected and failure_category is None)
    if executed < expected and failure_category is None:
        _fail("an incomplete rollout must declare failure_category")
    if executed == expected and failure_category is not None:
        _fail("a full executed prefix cannot declare an execution failure")
    if _strict_bool(row.get("execution_complete"), "case.execution_complete") is not execution_complete:
        _fail("case.execution_complete disagrees with frame/failure semantics")
    for name in ("position_rmse", "velocity_rmse", "position_ade", "velocity_ade"):
        _finite_metric_prefix(row.get(name), name=f"case.{name}", expected=expected,
                              executed=executed)
    finite_complete = bool(execution_complete)
    if _strict_bool(row.get("finite_rollout_complete"), "case.finite_rollout_complete") is not finite_complete:
        _fail("case.finite_rollout_complete disagrees with metric completion")

    scientific_status = row.get("scientific_status")
    if scientific_status != "not_assessed":
        _fail("case.scientific_status must remain not_assessed")
    if row.get("scientific_failure_category") is not None:
        _fail("case.scientific_failure_category must be null")
    if row.get("scientific_first_failure_frame") is not None:
        _fail("case.scientific_first_failure_frame must be null")
    _strict_false(row.get("future_state_inputs"), "case.future_state_inputs")
    _validate_score(row, expected=expected, executed=executed,
                    failure_category=failure_category,
                    execution_complete=execution_complete)

    if failure_category == "maximum_steps_limit":
        if maximum_steps is None or maximum_steps >= expected or maximum_steps != executed:
            _fail("maximum_steps_limit requires a shorter matching maximum_steps")
        if mode != "diagnostic":
            _fail("maximum_steps_limit is diagnostic-only")
    elif maximum_steps is not None and maximum_steps < expected and executed == maximum_steps:
        _fail("a bounded rollout must declare failure_category=maximum_steps_limit")

    trajectory_value = row.get("trajectory_output")
    trajectory_path = _resolve_path(trajectory_value, base=path.parent,
                                    name="case.trajectory_output")
    context = {
        "maximum_steps": maximum_steps,
        "expected_transitions": expected,
        "frames_executed": executed,
        "failure_category": failure_category,
        "execution_complete": execution_complete,
        "executed": executed_flag,
    }
    return context, case_id, row, trajectory_path


def _read_identity(dataset: h5py.Dataset, *, name: str, particles: int) -> np.ndarray:
    if dataset.shape != (particles,) or dataset.dtype.kind not in "iu":
        _fail(f"HDF5 {name} must be a one-dimensional integer axis")
    values = np.asarray(dataset[...])
    if values.dtype.kind == "u" and values.size and int(values.max()) > np.iinfo(np.int64).max:
        _fail(f"HDF5 {name} exceeds int64 identity range")
    return values.astype(np.int64, copy=False)


def _filesystem_identity(info: os.stat_result) -> tuple[int, ...]:
    """Return the stable identity fields used around one descriptor read."""
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(info.st_mode),
        int(info.st_nlink),
        int(info.st_size),
        int(info.st_mtime_ns),
        int(info.st_ctime_ns),
    )


def _directory_open_flags() -> int:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if not nofollow or not getattr(os, "O_DIRECTORY", 0):
        _fail("platform lacks O_NOFOLLOW/O_DIRECTORY for stable HDF5 opening")
    return os.O_RDONLY | os.O_DIRECTORY | nofollow | getattr(os, "O_CLOEXEC", 0)


def _file_open_flags() -> int:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if not nofollow:
        _fail("platform lacks O_NOFOLLOW for stable HDF5 opening")
    return os.O_RDONLY | nofollow | getattr(os, "O_CLOEXEC", 0)


def _open_directory_chain(path: Path) -> int:
    """Open every absolute directory component without following symlinks."""
    if not path.is_absolute():
        _fail("HDF5 parent directory must be absolute")
    flags = _directory_open_flags()
    try:
        current = os.open(path.anchor or os.sep, flags)
    except OSError as error:
        _fail(f"cannot open HDF5 parent root: {error}")
    try:
        for component in path.parts[1:]:
            try:
                next_fd = os.open(component, flags, dir_fd=current)
            except OSError as error:
                _fail(f"HDF5 parent component {component!r} is unsafe: {error}")
            os.close(current)
            current = next_fd
        return current
    except BaseException:
        try:
            os.close(current)
        except OSError:
            pass
        raise


def _read_fd_once(descriptor: int, *, expected_size: int, max_bytes: int) -> bytes:
    """Read exactly one bounded descriptor snapshot without opening a path."""
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        total = 0
        while True:
            remaining = max_bytes + 1 - total
            if remaining <= 0:
                _fail(f"HDF5 exceeds bounded size {max_bytes}")
            block = os.read(descriptor, min(1024 * 1024, remaining))
            if not block:
                break
            chunks.append(block)
            total += len(block)
        raw = b"".join(chunks)
    except OSError as error:
        _fail(f"cannot read HDF5 descriptor: {error}")
    if total != expected_size:
        _fail("HDF5 size changed while reading the descriptor")
    return raw


def _read_stable_hdf5_snapshot(path: Path) -> tuple[bytes, dict[str, Any]]:
    """Bind one regular HDF5 path and return only a stable byte snapshot.

    The pathname is never reopened after validation.  A directory-fd walk
    rejects parent symlinks, ``O_NOFOLLOW`` rejects a leaf symlink, and the
    file must have one filesystem hard link.  The descriptor is read twice;
    fd identity, path identity, byte count, and SHA-256 must agree before the
    in-memory snapshot is handed to h5py.  This keeps a pathname replacement
    or in-place mutation from redirecting the HDF5 parser.
    """
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        _fail("trajectory HDF5 path must be an absolute file path")
    parent_fd = _open_directory_chain(path.parent)
    descriptor: int | None = None
    try:
        try:
            path_before = os.lstat(path)
        except OSError as error:
            _fail(f"trajectory HDF5 does not exist: {path}: {error}")
        if not stat.S_ISREG(path_before.st_mode):
            _fail("trajectory HDF5 must be a regular file; symlinks are rejected")
        if path_before.st_nlink != 1:
            _fail("trajectory HDF5 must have exactly one filesystem hard link")
        if path_before.st_size < 1 or path_before.st_size > MAX_HDF5_BYTES:
            _fail(f"trajectory HDF5 exceeds bounded size {MAX_HDF5_BYTES}")

        try:
            descriptor = os.open(path.name, _file_open_flags(), dir_fd=parent_fd)
        except OSError as error:
            _fail(f"cannot open trajectory HDF5 without following links: {error}")
        fd_before = os.fstat(descriptor)
        identity_before = _filesystem_identity(fd_before)
        if not stat.S_ISREG(fd_before.st_mode):
            _fail("trajectory HDF5 descriptor is not a regular file")
        if fd_before.st_nlink != 1:
            _fail("trajectory HDF5 descriptor has multiple filesystem hard links")
        if identity_before != _filesystem_identity(path_before):
            _fail("trajectory HDF5 path identity drifted before the read")

        first = _read_fd_once(
            descriptor,
            expected_size=int(fd_before.st_size),
            max_bytes=MAX_HDF5_BYTES,
        )
        fd_after_first = os.fstat(descriptor)
        if _filesystem_identity(fd_after_first) != identity_before:
            _fail("trajectory HDF5 fd identity changed during the first read")
        if len(first) != int(fd_after_first.st_size):
            _fail("trajectory HDF5 fd size changed during the first read")
        first_sha256 = hashlib.sha256(first).hexdigest()

        # A second read from the same descriptor catches an in-place content
        # mutation even when a filesystem timestamp/size is preserved.
        second = _read_fd_once(
            descriptor,
            expected_size=int(fd_after_first.st_size),
            max_bytes=MAX_HDF5_BYTES,
        )
        fd_after_second = os.fstat(descriptor)
        if _filesystem_identity(fd_after_second) != identity_before:
            _fail("trajectory HDF5 fd identity changed during the second read")
        if len(second) != int(fd_after_second.st_size):
            _fail("trajectory HDF5 fd size changed during the second read")
        second_sha256 = hashlib.sha256(second).hexdigest()
        if first_sha256 != second_sha256 or first != second:
            _fail("trajectory HDF5 content hash changed between stable reads")

        try:
            path_after = os.lstat(path)
        except OSError as error:
            _fail(f"trajectory HDF5 path changed after the read: {error}")
        if _filesystem_identity(path_after) != _filesystem_identity(fd_after_second):
            _fail("trajectory HDF5 path identity changed after the read")
        return first, {
            "bytes": len(first),
            "sha256": first_sha256,
            "filesystem_identity_stable": True,
        }
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        try:
            os.close(parent_fd)
        except OSError:
            pass


def _reject_unsafe_hdf5_links(handle: h5py.File) -> int:
    """Reject external/soft links and virtual datasets before dereference."""
    pending: list[h5py.Group] = [handle]
    visited_groups: set[int] = set()
    visited_links = 0
    while pending:
        group = pending.pop()
        group_id = int(group.id.id)
        if group_id in visited_groups:
            continue
        visited_groups.add(group_id)
        for name in group.keys():
            visited_links += 1
            if visited_links > MAX_HDF5_LINKS:
                _fail("HDF5 link count exceeds the bounded limit")
            try:
                link = group.get(name, getlink=True)
            except (OSError, ValueError) as error:
                _fail(f"cannot inspect HDF5 link {name!r}: {error}")
            if not isinstance(link, h5py.HardLink):
                _fail(f"HDF5 contains a non-hard external/soft link at {name!r}")
            try:
                obj = group.get(name)
            except (OSError, ValueError) as error:
                _fail(f"cannot dereference HDF5 hard link {name!r}: {error}")
            if isinstance(obj, h5py.Group):
                pending.append(obj)
            elif isinstance(obj, h5py.Dataset):
                if bool(getattr(obj, "is_virtual", False)):
                    _fail(f"HDF5 contains a virtual dataset at {name!r}")
                if bool(getattr(obj, "external", ())):
                    _fail(f"HDF5 contains externally stored data at {name!r}")
            else:
                _fail(f"HDF5 contains an unsupported object at {name!r}")
    return visited_links


def _validate_hdf5(path: Path, *, context: Mapping[str, Any], case_id: str) -> dict[str, Any]:
    raw, file_identity = _read_stable_hdf5_snapshot(path)
    expected = int(context["expected_transitions"])
    executed = int(context["frames_executed"])
    failure_category = context["failure_category"]
    maximum_steps = context["maximum_steps"]
    if failure_category == "maximum_steps_limit":
        expected_hdf5_transitions = executed
    else:
        expected_hdf5_transitions = expected

    try:
        # The parser sees only the already-bound bytes, never the mutable
        # trajectory pathname.  Link inspection happens before any required
        # dataset is looked up or dereferenced.
        with h5py.File(io.BytesIO(raw), "r") as handle:
            link_count = _reject_unsafe_hdf5_links(handle)
            missing = REQUIRED_DATASETS - set(handle)
            if missing:
                _fail(f"HDF5 is missing datasets: {sorted(missing)}")
            if "future_state_inputs" not in handle.attrs:
                _fail("HDF5 future_state_inputs attribute is missing")
            _strict_false(handle.attrs["future_state_inputs"], "HDF5 future_state_inputs")
            if "autonomous_prediction" not in handle.attrs:
                _fail("HDF5 autonomous_prediction attribute is missing")
            _strict_true(handle.attrs["autonomous_prediction"], "HDF5 autonomous_prediction")
            if "case_id" in handle.attrs and handle.attrs["case_id"] != case_id:
                _fail("HDF5 case_id disagrees with the evaluation case")

            time_dataset = handle["time"]
            if len(time_dataset.shape) != 1:
                _fail("HDF5 time must be one-dimensional")
            frame_count = int(time_dataset.shape[0])
            if frame_count != expected_hdf5_transitions + 1:
                _fail(
                    "HDF5 frame count disagrees with completion semantics: "
                    f"expected {expected_hdf5_transitions + 1}, got {frame_count}")
            times = np.asarray(time_dataset[...], dtype=np.float64)
            if (times.shape != (frame_count,) or not np.isfinite(times).all()
                    or np.any(np.diff(times) <= 0)):
                _fail("HDF5 time must be finite and strictly increasing")

            position = handle["position"]
            velocity = handle["velocity"]
            if (len(position.shape) != 3 or position.shape[0] != frame_count
                    or position.shape[2] != 3):
                _fail("HDF5 position must have shape [frames, particles, 3]")
            if velocity.shape != position.shape:
                _fail("HDF5 velocity shape must equal position shape")
            particles = int(position.shape[1])
            if particles < 1:
                _fail("HDF5 trajectory must contain at least one particle")

            particle_id = _read_identity(handle["particle_id"], name="particle_id",
                                         particles=particles)
            particle_zone = _read_identity(handle["particle_zone"], name="particle_zone",
                                           particles=particles)
            identity = np.column_stack((particle_zone, particle_id))
            if len(np.unique(identity, axis=0)) != particles:
                _fail("HDF5 composite particle identities are not unique")

            valid_dataset = handle["valid"]
            if valid_dataset.shape != (frame_count, particles):
                _fail("HDF5 valid shape must be [frames, particles]")
            if valid_dataset.dtype.kind not in "biu":
                _fail("HDF5 valid must use an explicit binary dtype")
            valid_raw = np.asarray(valid_dataset[...])
            if not np.isin(valid_raw, (0, 1)).all():
                _fail("HDF5 valid must contain only 0/1 values")
            valid = valid_raw.astype(bool, copy=False)
            initial_valid = np.array(valid[0], dtype=bool, copy=True)
            if not initial_valid.any():
                _fail("HDF5 initial valid mask must contain an active particle")
            completed_frames = executed + 1
            if not np.all(valid[:completed_frames] == initial_valid[None, :]):
                _fail("HDF5 valid lifecycle changed inside the executed prefix")
            if completed_frames < frame_count and np.any(valid[completed_frames:]):
                _fail("HDF5 unexecuted frames must have valid=false")

            for name, dataset in (("position", position), ("velocity", velocity)):
                completed_values = np.asarray(dataset[:completed_frames])
                active_values = completed_values[valid[:completed_frames]]
                if not np.isfinite(active_values).all():
                    _fail(f"HDF5 active {name} values are not finite in the executed prefix")
                if completed_frames < frame_count:
                    tail = np.asarray(dataset[completed_frames:])
                    if not np.isnan(tail).all():
                        _fail(f"HDF5 unexecuted {name} values must be NaN")

            mass = handle["mass"]
            if mass.shape not in ((particles,), (frame_count, particles)):
                _fail("HDF5 mass must have shape [particles] or [frames, particles]")
            mass_values = np.asarray(mass[...], dtype=np.float64)
            initial_mass = mass_values if mass.ndim == 1 else mass_values[0]
            active_initial_mass = initial_mass[initial_valid]
            if (not np.isfinite(active_initial_mass).all()
                    or np.any(active_initial_mass <= 0)):
                _fail("HDF5 active mass must be finite and positive")
            if mass.ndim == 2:
                active_completed_mass = mass_values[:completed_frames, initial_valid]
                if not np.isfinite(active_completed_mass).all() or np.any(active_completed_mass <= 0):
                    _fail("HDF5 active temporal mass must be finite and positive")
                if not np.array_equal(active_completed_mass,
                                      np.broadcast_to(active_initial_mass,
                                                      active_completed_mass.shape)):
                    _fail("HDF5 active mass changed inside the executed prefix")
    except ValidationError:
        raise
    except (OSError, TypeError, ValueError) as error:
        _fail(f"cannot inspect stable HDF5 snapshot: {error}")

    return {
        "frame_count": frame_count,
        "transition_count": frame_count - 1,
        "particle_count": particles,
        "time_start": float(times[0]),
        "time_end": float(times[-1]),
        "executed_frame_count": completed_frames,
        "tail_frame_count": frame_count - completed_frames,
        "file_bytes": int(file_identity["bytes"]),
        "file_sha256": str(file_identity["sha256"]),
        "link_count": link_count,
        "filesystem_identity_stable": bool(file_identity["filesystem_identity_stable"]),
    }


def validate_receipt(evaluation_json: str | Path, trajectory_hdf5: str | Path | None = None,
                     *, case_id: str | None = None,
                     expected_transitions: int = DEFAULT_EXPECTED_TRANSITIONS) -> dict[str, Any]:
    """Validate one F3 evaluation case and trajectory without writing files."""
    expected_transitions = _strict_int(expected_transitions, "expected_transitions", minimum=1)
    evaluation_path = Path(evaluation_json).expanduser().resolve()
    context, selected_case_id, row, embedded_trajectory = _validate_evaluation(
        evaluation_path, case_id, expected_transitions)
    trajectory_path = embedded_trajectory if trajectory_hdf5 is None else _resolve_path(
        trajectory_hdf5, base=evaluation_path.parent, name="trajectory_hdf5")
    hdf5 = _validate_hdf5(trajectory_path, context=context, case_id=selected_case_id)
    complete = bool(context["execution_complete"])
    return {
        "schema": SCHEMA,
        "passed": True,
        "fail_closed": False,
        "diagnostic_only": True,
        "synthetic_only": False,
        "production_artifacts_touched": False,
        "qualification_credit": 0,
        "case_id": selected_case_id,
        "evaluation_json": str(evaluation_path),
        "trajectory_hdf5": str(trajectory_path),
        "expected_transitions": expected_transitions,
        "frames_executed": int(context["frames_executed"]),
        "complete": complete,
        "incomplete": not complete,
        "failure_category": context["failure_category"],
        "checks": {
            "case_binding": True,
            "shape": True,
            "time": True,
            "valid": True,
            "future_state_inputs": True,
            "completion_semantics": True,
            "trajectory_frames": hdf5["frame_count"],
            "trajectory_transitions": hdf5["transition_count"],
            "particle_count": hdf5["particle_count"],
            "time_start": hdf5["time_start"],
            "time_end": hdf5["time_end"],
            "executed_frame_count": hdf5["executed_frame_count"],
            "tail_frame_count": hdf5["tail_frame_count"],
            "trajectory_file_bytes": hdf5["file_bytes"],
            "trajectory_file_sha256": hdf5["file_sha256"],
            "trajectory_filesystem_identity_stable": hdf5["filesystem_identity_stable"],
            "hdf5_link_count": hdf5["link_count"],
        },
        "row_fields_checked": sorted(row.keys()),
    }


def run_validation(evaluation_json: str | Path, trajectory_hdf5: str | Path | None = None,
                   *, case_id: str | None = None,
                   expected_transitions: int = DEFAULT_EXPECTED_TRANSITIONS) -> dict[str, Any]:
    """Return a JSON-safe pass/fail receipt; failures always remain fail-closed."""
    try:
        return validate_receipt(
            evaluation_json, trajectory_hdf5, case_id=case_id,
            expected_transitions=expected_transitions)
    except Exception as error:
        return {
            "schema": SCHEMA,
            "passed": False,
            "fail_closed": True,
            "diagnostic_only": True,
            "synthetic_only": False,
            "production_artifacts_touched": False,
            "qualification_credit": 0,
            "failure_reason": str(error),
        }


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evaluation_json", type=Path)
    parser.add_argument("--trajectory", type=Path, default=None,
                        help="optional read-only trajectory HDF5 override")
    parser.add_argument("--case-id", default=None)
    parser.add_argument("--expected-transitions", type=int,
                        default=DEFAULT_EXPECTED_TRANSITIONS)
    args = parser.parse_args(argv)
    result = run_validation(
        args.evaluation_json, args.trajectory, case_id=args.case_id,
        expected_transitions=args.expected_transitions)
    print(_canonical_json(result))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
