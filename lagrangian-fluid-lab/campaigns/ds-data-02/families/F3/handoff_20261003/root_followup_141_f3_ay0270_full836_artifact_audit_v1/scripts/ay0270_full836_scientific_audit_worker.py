#!/usr/bin/env python3
"""Root-owned AY0270 full-836 scientific artifact audit.

This worker is deliberately disabled in the source package.  When Root registers
it as a CPU ``audit`` task, it reads the existing trajectory HDF5 read-only and
streams its SHA-256.  It then reuses the approved
``f3_full_temporal_verify_v1`` kernel for bounded, full-frame checks of time,
3-D position/velocity, composite particle identity, validity and mass
lifecycle.  The adapter adds the F3 typed schema checks that the generic kernel
does not own: required type/Mk fields, per-frame type counts, the report's 836
frame time/count ledger, finite density/pressure/mass fields, and closure to
GenCase, the completed native receipt, the preserved typed request, and the
completed conversion report.

The source package never invokes this worker or opens H5/BI4/CSV/DAT/VTK.  A
successful new audit receipt is an independent fact.  It cannot rewrite the
old typed receipt, turn its null OS returncode into zero, settle its old
reservation, grant production/Q-N credit, or collapse the converter's legacy
physical scope into the native canonical scope.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from typing import Any


SCHEMA = "ds02.strict-cpu.f3-ay0270-full836-scientific-artifact-audit.v1"
TEMPORAL_SCHEMA = "core.f3.full_temporal_verification.v1"
OLD_RECEIPT_STATUSES = {"running", "interrupted_unfinalized"}
HEX64 = set("0123456789abcdefABCDEF")


class AuditError(ValueError):
    """A strict source binding or scientific artifact check failed."""


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


def is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in HEX64 for c in value)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_bytes_sha256(path: Path, expected: str, *, label: str) -> bytes:
    require(path.is_file(), f"{label} is missing: {path}")
    raw = path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    require(actual == expected, f"{label} changed: {actual} != {expected}")
    return raw


def load_json_ref(ref: dict[str, Any], *, label: str) -> tuple[Path, dict[str, Any]]:
    require(isinstance(ref, dict), f"{label} reference must be an object")
    path_text = ref.get("path")
    expected = ref.get("sha256")
    require(isinstance(path_text, str) and Path(path_text).is_absolute(),
            f"{label} path must be absolute")
    require(is_sha256(expected), f"{label} requires a SHA-256")
    path = Path(path_text)
    raw = read_bytes_sha256(path, expected, label=label)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AuditError(f"{label} must be UTF-8 JSON") from error
    require(isinstance(value, dict), f"{label} must be a JSON object")
    return path, value


def write_new_json(path: Path, value: dict[str, Any]) -> None:
    """Publish a new audit receipt without replacing any existing evidence."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        offset = 0
        while offset < len(data):
            offset += os.write(fd, data[offset:])
        os.fsync(fd)
    finally:
        os.close(fd)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _load_temporal_kernel(path: Path, expected_sha256: str):
    actual = sha256_file(path)
    require(actual == expected_sha256,
            f"approved temporal kernel changed: {actual} != {expected_sha256}")
    # The integration lab path is explicit in the Root request.  The kernel
    # itself resolves scripts.core_dataset relative to this lab root.
    sys.path.insert(0, str(path.resolve().parents[1]))
    spec = importlib.util.spec_from_file_location("ds02_approved_f3_temporal_kernel", path)
    require(spec is not None and spec.loader is not None, "cannot load temporal kernel")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    require(getattr(module, "SCHEMA", None) == TEMPORAL_SCHEMA,
            "unexpected temporal kernel schema")
    require(hasattr(module, "_verify_case"),
            "approved temporal kernel has no bounded case verifier")
    return module


class _OneCaseDataset:
    """Minimal adapter for the approved kernel; no CoreDataset state materialization."""

    def __init__(self, trajectory: Path, case_id: str):
        self.data_root = trajectory.parent
        self.case_id = case_id

    def record(self, case_id: str) -> dict[str, Any]:
        require(case_id == self.case_id, "temporal kernel requested an unexpected case")
        return {
            "case_id": case_id,
            "family": "F3",
            "split": "production",
            "hdf5": "trajectory.h5",
            "known_inputs_sha256": "attested-outside-core-dataset-manifest",
        }


def _report_block_counts(report: dict[str, Any]) -> tuple[dict[int, int], dict[int, int]]:
    blocks = report.get("typed_identity", {}).get("blocks")
    require(isinstance(blocks, list) and blocks, "typed_identity.blocks is missing")
    type_counts: dict[int, int] = {}
    mk_counts: dict[int, int] = {}
    for block in blocks:
        require(isinstance(block, dict), "typed identity block must be an object")
        count = block.get("count")
        type_value = block.get("type")
        mk_value = block.get("mk")
        require(isinstance(count, int) and count >= 0, "typed block count is invalid")
        require(isinstance(type_value, int) and isinstance(mk_value, int),
                "typed block type/Mk is invalid")
        type_counts[type_value] = type_counts.get(type_value, 0) + count
        mk_counts[mk_value] = mk_counts.get(mk_value, 0) + count
    return type_counts, mk_counts


def _counts(values, *, active=None) -> dict[int, int]:
    import numpy as np
    array = np.asarray(values)
    if active is not None:
        array = array[np.asarray(active, dtype=bool)]
    if array.size == 0:
        return {}
    unique, counts = np.unique(array, return_counts=True)
    return {int(key): int(value) for key, value in zip(unique.tolist(), counts.tolist())}


def _counts_match(actual: dict[int, int], expected: dict[int, int]) -> bool:
    """Compare count maps while preserving explicit zero-valued report keys."""
    keys = set(actual) | set(expected)
    return all(actual.get(key, 0) == expected.get(key, 0) for key in keys)


def _shape_kind(dataset, frames: int, particles: int, *, label: str):
    shape = tuple(int(value) for value in dataset.shape)
    if shape == (particles,):
        return "static"
    require(shape == (frames, particles), f"{label} has unexpected shape {shape}")
    return "dynamic"


def _finite_chunk(dataset, start: int, stop: int, *, label: str) -> None:
    import numpy as np
    values = np.asarray(dataset[start:stop])
    require(np.isfinite(values).all(), f"nonfinite {label} in frames {start}:{stop}")


def _finite_dataset(dataset, *, label: str) -> None:
    import numpy as np
    values = np.asarray(dataset[...])
    require(np.isfinite(values).all(), f"nonfinite {label}")


def _audit_typed_fields(*, trajectory: Path, report: dict[str, Any], expected_frames: int,
                        expected_particles: int, expected_type_counts: dict[int, int],
                        expected_mk_counts: dict[int, int]) -> dict[str, Any]:
    """Read and validate all stored H5 identity/state axes in Root's CPU job."""
    import h5py
    import numpy as np

    required = {
        "time", "position", "velocity", "valid", "particle_id", "particle_zone",
        "initial_type", "initial_mk", "initial_mass", "mass", "density", "pressure", "type",
    }
    lifecycle = report.get("lifecycle", {})
    frame_summary = lifecycle.get("frame_summary")
    require(isinstance(frame_summary, list) and len(frame_summary) == expected_frames,
            "conversion report does not contain the full 836-frame lifecycle ledger")

    with h5py.File(trajectory, "r") as handle:
        missing = sorted(required - set(handle))
        require(not missing, f"trajectory is missing required fields: {missing}")
        position = handle["position"]
        velocity = handle["velocity"]
        require(tuple(position.shape) == (expected_frames, expected_particles, 3),
                f"position is not [836,179208,3]: {position.shape}")
        require(tuple(velocity.shape) == tuple(position.shape),
                "velocity does not have the position N×3 shape")
        times = np.asarray(handle["time"][...], dtype=np.float64)
        require(times.shape == (expected_frames,), "time axis is not length 836")
        require(np.isfinite(times).all() and np.all(np.diff(times) > 0),
                "time axis is not finite and strictly increasing")

        particle_id = np.asarray(handle["particle_id"][...])
        particle_zone = np.asarray(handle["particle_zone"][...])
        require(particle_id.shape == (expected_particles,), "particle_id shape is invalid")
        require(particle_zone.shape == (expected_particles,), "particle_zone shape is invalid")
        require(particle_id.dtype.kind in "iu" and particle_zone.dtype.kind in "iu",
                "particle identity axes must be integer")
        order = np.lexsort((particle_id.astype(np.int64), particle_zone.astype(np.int64)))
        duplicate = ((particle_id[order[1:]] == particle_id[order[:-1]])
                     & (particle_zone[order[1:]] == particle_zone[order[:-1]]))
        require(not bool(np.any(duplicate)), "duplicate (particle_zone,particle_id) identity")

        static_type_kind = _shape_kind(handle["type"], expected_frames, expected_particles,
                                       label="type")
        _shape_kind(handle["initial_type"], 1, expected_particles, label="initial_type")
        _shape_kind(handle["initial_mk"], 1, expected_particles, label="initial_mk")
        _shape_kind(handle["initial_mass"], 1, expected_particles, label="initial_mass")
        require(handle["initial_type"].dtype.kind in "iu", "initial_type must be integer")
        require(handle["initial_mk"].dtype.kind in "iu", "initial_mk must be integer")
        initial_type = np.asarray(handle["initial_type"][...])
        initial_mk = np.asarray(handle["initial_mk"][...])
        require(_counts(initial_type) == expected_type_counts,
                f"initial type counts differ: {_counts(initial_type)} != {expected_type_counts}")
        require(_counts(initial_mk) == expected_mk_counts,
                f"initial Mk counts differ: {_counts(initial_mk)} != {expected_mk_counts}")

        # The generic kernel checks position/velocity/mass/valid transitions.
        # This pass covers the remaining typed fields and rebinds the report's
        # complete frame ledger without materializing all frames at once.
        valid = handle["valid"]
        require(tuple(valid.shape) == (expected_frames, expected_particles),
                "valid lifecycle shape is invalid")
        require(valid.dtype.kind in "biu", "valid lifecycle is not binary storage")
        scalar_kinds = {
            name: _shape_kind(handle[name], expected_frames, expected_particles, label=name)
            for name in ("density", "pressure")
        }
        for name, kind in scalar_kinds.items():
            if kind == "static":
                _finite_dataset(handle[name], label=name)
        mass_kind = _shape_kind(handle["mass"], expected_frames, expected_particles, label="mass")
        initial_mass = np.asarray(handle["initial_mass"][...], dtype=np.float64)
        require(np.isfinite(initial_mass).all() and np.all(initial_mass > 0),
                "initial_mass is not finite and positive")
        static_mass = (np.asarray(handle["mass"][...], dtype=np.float64)
                       if mass_kind == "static" else None)
        if static_mass is not None:
            require(np.isfinite(static_mass).all() and np.all(static_mass > 0),
                    "static mass is not finite and positive")
        static_type = (np.asarray(handle["type"][...])
                       if static_type_kind == "static" else None)
        require(handle["type"].dtype.kind in "iu", "type must be integer")

        chunk = 8
        observed_times = []
        for start in range(0, expected_frames, chunk):
            stop = min(start + chunk, expected_frames)
            raw_valid = np.asarray(valid[start:stop])
            require(np.isin(raw_valid, (0, 1)).all(),
                    f"valid contains non-binary values in frames {start}:{stop}")
            active = raw_valid.astype(bool)
            for name, kind in scalar_kinds.items():
                if kind == "dynamic":
                    _finite_chunk(handle[name], start, stop, label=name)
            if mass_kind == "dynamic":
                _finite_chunk(handle["mass"], start, stop, label="mass")
            _finite_chunk(handle["position"], start, stop, label="position")
            _finite_chunk(handle["velocity"], start, stop, label="velocity")
            if static_type_kind == "dynamic":
                type_block = np.asarray(handle["type"][start:stop])
            else:
                type_block = np.broadcast_to(static_type,
                                             (stop - start, expected_particles))
            for offset in range(stop - start):
                frame = start + offset
                row = frame_summary[frame]
                actual_time = float(times[frame])
                observed_times.append(actual_time)
                require(row.get("frame") == frame, f"report frame ledger index drift at {frame}")
                require(actual_time == float(row.get("time")),
                        f"H5/report time mismatch at frame {frame}")
                active_row = active[offset]
                actual_active = int(active_row.sum())
                actual_type_counts = _counts(type_block[offset], active=active_row)
                actual_mk_counts = _counts(initial_mk, active=active_row)
                expected_counts = {int(k): int(v) for k, v in row.get("type_counts", {}).items()}
                require(actual_active == int(row.get("active_particles")),
                        f"active particle count mismatch at frame {frame}")
                require(_counts_match(actual_type_counts, expected_counts),
                        f"type counts mismatch at frame {frame}: {actual_type_counts} != {expected_counts}")
                require(actual_mk_counts == expected_mk_counts,
                        f"Mk counts mismatch at frame {frame}")
                require(int(row.get("missing_particles")) == expected_particles - actual_active,
                        f"missing particle ledger mismatch at frame {frame}")
                require(int(row.get("missing_particles")) == 0,
                        f"unexpected missing particles at frame {frame}")
        require(len(observed_times) == expected_frames, "full time coverage was not observed")

    return {
        "required_fields": sorted(required),
        "frames": expected_frames,
        "particles": expected_particles,
        "position_shape": [expected_frames, expected_particles, 3],
        "n3_shape_verified": True,
        "time_axis_verified_against_report": True,
        "uid_composite_unique": True,
        "uid_lifecycle_missing_count": 0,
        "type_mk_verified_all_frames": True,
        "finite_position_velocity_density_pressure_mass": True,
        "report_frame_ledger_verified": True,
        "source_arrays_modified": False,
    }


def audit(binding_path: Path, output_path: Path | None = None) -> dict[str, Any]:
    binding_path = Path(binding_path).resolve()
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    require(isinstance(binding, dict) and binding.get("schema") ==
            "ds02.fresh141.ay0270-full836-audit-binding.v1", "unexpected audit binding schema")
    require(binding.get("source_only") is True, "audit binding must remain source-only")
    require(binding.get("execution_allowed") is False and binding.get("launch_allowed") is False,
            "audit binding must be disabled")

    expected = binding["expected"]
    case_id = expected["case_id"]
    physical_case_id = expected["physical_case_id"]
    canonical_condition = expected["canonical_physical_condition_sha256"]
    expected_frames = int(expected["frames"])
    expected_particles = int(expected["particles"])

    refs = binding["metadata_refs"]
    _, old_receipt = load_json_ref(refs["old_typed_receipt"], label="old typed receipt")
    _, report = load_json_ref(refs["conversion_report"], label="conversion report")
    _, native = load_json_ref(refs["native_receipt"], label="native receipt")
    _, gencase = load_json_ref(refs["gencase_receipt"], label="GenCase receipt")
    _, prepared = load_json_ref(refs["prepared_input_report"], label="prepared input report")
    _, typed_request = load_json_ref(refs["typed_request"], label="typed request")
    _, source_owner = load_json_ref(refs["source_owner"], label="source owner")
    _, historical_rejection = load_json_ref(refs["historical_entry_rejection"], label="historical rejection")
    _, recovery_audit = load_json_ref(refs["fresh140_process_audit"], label="fresh140 recovery audit")
    _, authority_checkpoint = load_json_ref(refs["authority_checkpoint"], label="authority checkpoint")
    _, census = load_json_ref(refs["census"], label="source census")
    _, checkpoint = load_json_ref(refs["checkpoint_173"], label="checkpoint 173")

    old_request = old_receipt.get("request", {})
    require(old_receipt.get("status") in OLD_RECEIPT_STATUSES,
            "old typed receipt is no longer in the preserved unknown lifecycle")
    require(old_receipt.get("returncode") is None,
            "old typed receipt returncode must remain null")
    require(old_request.get("attempt_id") == expected["old_attempt_id"],
            "old typed attempt identity changed")
    require(old_request.get("case_id") == case_id, "old typed case identity differs")
    require(old_request.get("physical_case_id") == physical_case_id,
            "old typed physical identity differs")
    require(old_request.get("physical_condition_sha256") == canonical_condition,
            "old typed canonical physical condition differs")
    old_native_binding = old_request.get("native_full836_binding", {})
    require("expected_saved_frames" not in old_request,
            "old typed top-level frame alias unexpectedly appeared")
    require(old_native_binding.get("expected_saved_frames") == expected_frames,
            "old typed nested native saved frame expectation differs")
    require(old_native_binding.get("returncode") == 0 and
            old_native_binding.get("status") == "completed",
            "old typed nested native binding is not completed/0")
    require(old_native_binding.get("save_interval_s") == 0.01 and
            old_native_binding.get("time_window_s") == [0.0, 8.35],
            "old typed nested native recipe differs")
    old_native_ref = old_native_binding.get("receipt", {})
    require(old_native_ref.get("path") == refs["native_receipt"]["path"] and
            old_native_ref.get("sha256") == refs["native_receipt"]["sha256"],
            "old typed nested native receipt binding differs")

    require(report.get("conversion_status") == "completed", "conversion report is not complete")
    require(report.get("frames") == expected_frames and report.get("particles") == expected_particles,
            "conversion report full836 counts differ")
    require(report.get("solver_dimension", {}).get("solver_dimension") == 3,
            "conversion report is not 3-D")
    report_scope = report.get("hash_scopes", {}).get("physical_condition", {})
    report_scope_sha = report.get("hash_scopes", {}).get("physical_condition_sha256")
    require(report_scope.get("physical_case_id") == physical_case_id,
            "conversion report physical scope differs")
    require(report_scope_sha == expected["converter_legacy_scope_sha256"],
            "conversion report legacy scope differs")
    require(report.get("output_hdf5") == binding["h5_producer_attestation"]["path"],
            "conversion report H5 path differs")
    producer_h5_sha = binding["h5_producer_attestation"]["producer_reported_sha256"]
    require(report.get("output_sha256") == producer_h5_sha,
            "conversion report producer H5 attestation differs")
    require(report.get("storage_protocol", {}).get("verified_published_output_sha256") == producer_h5_sha,
            "conversion report storage closure differs")
    require(report.get("partvtk_validation", {}).get("all_passed") is True,
            "conversion report PartVTK producer metadata is not all_passed")
    require(report.get("typed_identity", {}).get("initial_exclusion_ledger", {}).get("count") == 0,
            "conversion report has an initial exclusion count")
    expected_type_counts, expected_mk_counts = _report_block_counts(report)
    require(expected_type_counts == {0: 111708, 3: 67500},
            f"unexpected report type block counts: {expected_type_counts}")
    require(expected_mk_counts == {10: 111708, 1: 67500},
            f"unexpected report Mk block counts: {expected_mk_counts}")

    native_request = native.get("request", {})
    require(native.get("status") == "completed" and native.get("returncode") == 0,
            "canonical native receipt is not completed/0")
    require(native_request.get("case_id") == case_id and
            native_request.get("physical_case_id") == physical_case_id and
            native_request.get("physical_condition_sha256") == canonical_condition,
            "canonical native binding differs")
    require(native_request.get("expected_saved_frames") == expected_frames,
            "canonical native frame expectation differs")
    require(native_request.get("complete_event_window_s") == [0.0, 8.35],
            "canonical native time window differs")
    require(native_request.get("save_interval_s") == 0.01,
            "canonical native save interval differs")

    require(gencase.get("status") == "completed" and gencase.get("returncode") == 0,
            "genuine parent GenCase receipt is not completed/0")
    require(gencase.get("total_particles") == expected_particles and
            gencase.get("fluid_particles") == 67500 and
            gencase.get("solver_dimension_from_gencase") == 3,
            "genuine parent GenCase counts/dimension differ")
    require(prepared.get("case_id") == case_id and
            prepared.get("physical_case_id") == physical_case_id and
            prepared.get("physical_condition_sha256") == canonical_condition,
            "prepared input report identity differs")
    counts = prepared.get("generated_particle_counts", {})
    require(counts.get("fixed") == 111708 and counts.get("fluid") == 67500 and
            counts.get("moving") == 0 and counts.get("floating") == 0,
            "prepared input report particle counts differ")
    require(prepared.get("expected_frames") == expected_frames and
            prepared.get("save_interval_s") == 0.01 and
            prepared.get("physical_window_s") == [0.0, 8.35],
            "prepared input report recipe differs")

    require(typed_request.get("case_id") == case_id and
            typed_request.get("physical_case_id") == physical_case_id and
            typed_request.get("physical_condition_sha256") == canonical_condition,
            "preserved typed request identity differs")
    require(source_owner.get("case_id") == case_id, "source owner case differs")
    owner_condition = source_owner.get("canonical_condition", {})
    require(owner_condition.get("physical_case_id") == physical_case_id and
            owner_condition.get("physical_condition_sha256") == canonical_condition,
            "source owner canonical physical binding differs")
    owner_native = source_owner.get("native_full836", {})
    require(owner_native.get("expected_saved_frames") == expected_frames and
            owner_native.get("returncode") == 0 and owner_native.get("status") == "completed",
            "source owner native binding is not completed/0 full836")
    owner_native_receipt = owner_native.get("receipt", {})
    require(owner_native_receipt.get("path") == refs["native_receipt"]["path"] and
            owner_native_receipt.get("sha256") == refs["native_receipt"]["sha256"],
            "source owner native receipt differs")
    require(historical_rejection.get("actual_tool_exit") == 1 and
            historical_rejection.get("runtime_job_started") is False and
            historical_rejection.get("conversion_started") is False,
            "historical entry rejection evidence changed semantics")
    require(recovery_audit.get("attempt_id") == expected["old_attempt_id"] and
            recovery_audit.get("recovery_state") ==
            "unfinalized_receipt_historical_processes_absent_no_ticks_no_current_reservation",
            "fresh140 recovery audit identity/state changed")
    historical_receipt = recovery_audit.get("historical_receipt", {})
    require(historical_receipt.get("status") in OLD_RECEIPT_STATUSES and
            historical_receipt.get("returncode") is None,
            "fresh140 recovery audit does not preserve old receipt uncertainty")
    require(recovery_audit.get("current_authoritative_checkpoint", {}).get(
                "matching_active_reservation_present") is False,
            "fresh140 recovery audit does not disclose its no-reservation snapshot")
    require(authority_checkpoint.get("schema") == "ds02.stage1.f3.fresh139.pipeline-census.v1",
            "source authority checkpoint schema changed")
    require(census.get("schema") == "ds02.stage1.f3.fresh139.remaining14.v1",
            "source census schema changed")
    require(checkpoint.get("checkpoint") == 173,
            "bound live checkpoint is not the reviewed checkpoint 173")

    temporal_ref = binding["approved_temporal_kernel"]
    kernel_path = Path(temporal_ref["path"])
    temporal = _load_temporal_kernel(kernel_path, temporal_ref["sha256"])
    trajectory = Path(binding["h5_producer_attestation"]["path"])
    require(trajectory.is_file(), "published trajectory H5 is missing")
    observed_h5_sha = sha256_file(trajectory)
    require(observed_h5_sha == producer_h5_sha,
            "observed trajectory H5 SHA differs from producer report")

    dataset = _OneCaseDataset(trajectory, case_id)
    temporal_case = temporal._verify_case(
        dataset, case_id, source_sha256=observed_h5_sha,
        frame_chunk_size=8, max_chunk_bytes=512 * 1024 * 1024,
    )
    require(temporal_case.get("frame_count") == expected_frames and
            temporal_case.get("particle_count") == expected_particles and
            temporal_case.get("checked_transition_count") == expected_frames - 1,
            "approved temporal kernel did not cover all 835 transitions")
    require(temporal_case.get("full_temporal_scan") is True,
            "approved temporal kernel did not report full scan")

    field_audit = _audit_typed_fields(
        trajectory=trajectory, report=report, expected_frames=expected_frames,
        expected_particles=expected_particles, expected_type_counts=expected_type_counts,
        expected_mk_counts=expected_mk_counts,
    )

    result = {
        "schema": SCHEMA,
        "artifact_integrity_status": "completed",
        "worker_returncode": 0,
        "finished_at_utc": now_utc(),
        "case_id": case_id,
        "physical_identity": {
            "physical_case_id": physical_case_id,
            "canonical_native_condition_sha256": canonical_condition,
            "converter_legacy_scope_sha256": expected["converter_legacy_scope_sha256"],
            "census_alias": binding["physical_identity"]["census_alias"],
            "alias_is_not_receipt_identity": True,
        },
        "source_conversion_lifecycle": {
            "attempt_id": old_request.get("attempt_id"),
            "receipt_status": old_receipt.get("status"),
            "receipt_returncode": old_receipt.get("returncode"),
            "top_level_expected_saved_frames_absent": "expected_saved_frames" not in old_request,
            "nested_native_expected_saved_frames": old_native_binding.get("expected_saved_frames"),
            "old_tool_status": expected["old_tool_status"],
            "source_receipt_edited": False,
            "source_conversion_reclassified": False,
            "old_os_exit_zero_claim": False,
        },
        "historical_recovery_evidence": {
            "fresh140_recovery_audit_sha256": refs["fresh140_process_audit"]["sha256"],
            "old_launcher_pid": recovery_audit["historical_processes"]["launcher_pid"],
            "old_child_pid": recovery_audit["historical_processes"]["child_pid_recorded_in_receipt"],
            "historical_start_ticks": None,
            "probe_is_historical_and_must_be_recaptured_by_root": True,
            "old_receipt_reclassified": False,
            "checkpoint_173_sha256": refs["checkpoint_173"]["sha256"],
        },
        "producer_attestation": {
            "conversion_report_sha256": refs["conversion_report"]["sha256"],
            "producer_reported_trajectory_sha256": producer_h5_sha,
            "verified_trajectory_sha256": observed_h5_sha,
            "native_receipt_sha256": refs["native_receipt"]["sha256"],
            "gencase_receipt_sha256": refs["gencase_receipt"]["sha256"],
            "partvtk_report_metadata_all_passed": True,
        },
        "approved_temporal_kernel": {
            "path": str(kernel_path),
            "sha256": temporal_ref["sha256"],
            "schema": TEMPORAL_SCHEMA,
            "full_temporal_scan": True,
            "checked_transitions": expected_frames - 1,
            "position_velocity_n3": True,
            "uid_and_mass_validity_lifecycle": True,
        },
        "field_audit": field_audit,
        "report_frame_ledger": {
            "frames": expected_frames,
            "times_compared_to_report": True,
            "type_counts_compared_all_frames": True,
            "missing_particles_all_frames": 0,
        },
        "audit_scope": {
            "h5_read_by_root_worker": True,
            "h5_hashed_by_root_worker": True,
            "arrays_decoded_by_source_agent": False,
            "source_arrays_modified": False,
            "production_approval": "none",
            "q_n": "not_granted",
            "independent_case_count_increment": 0,
        },
        "future_outputs": {
            "audit_receipt_sha256": None,
            "audit_report_sha256": None,
            "downstream_xmf_sha256": None,
            "visual_decision": None,
        },
    }
    if output_path is not None:
        write_new_json(Path(output_path), result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = audit(args.binding, args.output)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
