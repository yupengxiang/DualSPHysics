#!/usr/bin/env python3
"""Perform one read-only F4 supportcap r002 CPU-canary preflight only.

This entry point has no tracer, solver, GPU, scheduler, queue, registry, or
ledger path. A passing preflight does not grant or start runtime execution.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
from datetime import datetime, timezone
from typing import Any, Callable


_THREAD_ENV = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")

LAB = Path(__file__).resolve().parents[1]
RECIPE_REL = Path(
    "campaigns/core-v1/material/candidates/f4-supportcap-affine-query-bound-v3/"
    "r002-static-design-v3/recipe.json"
)
SCOPE_DIR = LAB / (
    "campaigns/core-v1/material/candidates/f4-supportcap-affine-query-bound-v3/"
    "cpu-native-canary-preflight-r002-v1"
)
AUTHORIZATION = SCOPE_DIR / "authorization.json"
RECEIPT = SCOPE_DIR / "preflight-receipt.json"
RECIPE = LAB / RECIPE_REL
SOURCE_REL = Path(
    "campaigns/core-v1/cfd/f4-tallwall120-archives-v2/"
    "f4-tallwall120-qualification-cell-14/product/trajectory.h5"
)
SOURCE = LAB / SOURCE_REL
OUTPUT_DIR = LAB / (
    "campaigns/core-v1/material/evidence/"
    "f4-supportcap-affine-query-bound-v3-cpu-native-canary-r002"
)
SCHEMA = "core.material.f4.supportcap_affine_query_bound.r002_cpu_canary_preflight.v1"
AUTH_SCHEMA = "core.material.f4.supportcap_affine_query_bound.r002_cpu_canary_preflight_authorization.v1"
ATTEMPT_ID = "f4-supportcap-affine-query-bound-v3-cpu-native-canary-r002"
ATTEMPT_REL = Path("campaigns/core-v1/material/evidence") / ATTEMPT_ID
SOURCE_SHA256 = "91846866c177e4c3036b7ef92c33a4e0bde7d9e8993efb01dde300811b7c096e"
SOURCE_BYTES = 10_326_356_548
SOURCE_FRAMES = 1086
SOURCE_PARTICLES = 217_485
FRAME_START = 0
FRAME_STOP = 41
MIN_RAM_BYTES = 16 * 1024**3
MIN_DISK_BYTES = 8 * 1024**3
MAX_STATIC_BINDING_BYTES = 2 * 1024**2
if not hasattr(os, "O_NOFOLLOW"):
    raise RuntimeError("this one-shot preflight requires O_NOFOLLOW support")
REQUIRED_STATIC_BINDINGS = {
    str(RECIPE_REL),
    "campaigns/core-v1/material/candidates/f4-supportcap-affine-query-bound-v3/r002-static-design-v3/review-v1.json",
    "campaigns/core-v1/material/candidates/f4-supportcap-affine-query-bound-v3/candidate-card-v3.json",
    "campaigns/core-v1/material/candidates/f4-supportcap-affine-query-bound-v3/terra-high-root-review-v4.json",
    "scripts/core_material.py",
    "scripts/f4_tallwall120_material.py",
    "scripts/f4_supportcap_affine_query_bound_candidate_v3.py",
    "scripts/f4_supportcap_r002_cpu_canary_preflight_v1.py",
    "tests/test_f4_supportcap_r002_cpu_canary_preflight_v1.py",
}
_THREAD_ENV_ORIGINAL: dict[str, str | None] | None = None
_CUDA_VISIBLE_ORIGINAL: str | None = None


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_stream(stream) -> str:
    digest = hashlib.sha256()
    stream.seek(0)
    for block in iter(lambda: stream.read(8 << 20), b""):
        digest.update(block)
    stream.seek(0)
    return digest.hexdigest()


def configure_cpu_preflight_environment() -> dict[str, Any]:
    """Set limits only when the CLI is invoked, never as an import side effect."""
    global _THREAD_ENV_ORIGINAL, _CUDA_VISIBLE_ORIGINAL
    _THREAD_ENV_ORIGINAL = {name: os.environ.get(name) for name in _THREAD_ENV}
    _CUDA_VISIBLE_ORIGINAL = os.environ.get("CUDA_VISIBLE_DEVICES")
    for name in _THREAD_ENV:
        os.environ[name] = "1"
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    return {
        "thread_environment_original": _THREAD_ENV_ORIGINAL,
        "CUDA_VISIBLE_DEVICES_original": _CUDA_VISIBLE_ORIGINAL,
    }


def validate_authorization(value: dict[str, Any]) -> None:
    scope = value.get("authorization", {})
    limits = value.get("preflight_contract", {})
    source = limits.get("source", {})
    controls = value.get("execution_controls", {})
    expected = {
        "schema": AUTH_SCHEMA,
        "status": "authorized_one_cpu_native_canary_preflight_runtime_not_authorized",
    }
    if any(value.get(key) != wanted for key, wanted in expected.items()):
        raise ValueError("missing or unexpected F4 r002 preflight authorization")
    if not (
        scope.get("attempt_id") == ATTEMPT_ID
        and scope.get("candidate_id") == "f4_supportcap_affine_query_bound_v3"
        and scope.get("grants_one_cpu_native_canary_preflight") is True
        and scope.get("grants_runtime_execution") is False
        and limits.get("max_preflight_attempts") == 1
        and limits.get("same_input_retry_allowed") is False
        and limits.get("native_rows_inclusive") == [FRAME_START, FRAME_STOP]
        and limits.get("source_sha256") == SOURCE_SHA256
        and limits.get("seed_denominator") == 512
        and limits.get("q") == 0.5
        and limits.get("dp_m") == 0.0075
        and limits.get("substeps") == 2
        and limits.get("output_namespace") == str(ATTEMPT_REL / "trace.h5")
        and source.get("path") == str(SOURCE_REL)
        and source.get("bytes") == SOURCE_BYTES
        and source.get("sha256") == SOURCE_SHA256
        and source.get("frame_count") == SOURCE_FRAMES
        and source.get("particle_count") == SOURCE_PARTICLES
        and controls.get("tracer_started") is False
        and controls.get("solver_started") is False
        and controls.get("gpu_started") is False
        and controls.get("queue_or_scheduler_started") is False
        and controls.get("t2_started") is False
        and controls.get("registry_mutation") == 0
        and controls.get("ledger_mutation") == 0
    ):
        raise ValueError("authorization does not bind the one-shot preflight-only scope")


def validate_static_bindings(value: dict[str, Any], *, lab: Path = LAB) -> None:
    bindings = value.get("static_bindings", [])
    by_path = {binding.get("path"): binding for binding in bindings}
    if len(by_path) != len(bindings) or not REQUIRED_STATIC_BINDINGS.issubset(by_path):
        missing = sorted(REQUIRED_STATIC_BINDINGS - set(by_path))
        raise ValueError(f"preflight authorization lacks required static bindings: {missing}")
    payloads: dict[str, bytes] = {}
    for binding in bindings:
        relative = Path(binding["path"])
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or relative.suffix.lower() not in {".json", ".py", ".md", ".txt"}
        ):
            raise ValueError(f"preflight authorization contains a forbidden static binding: {relative}")
        path = lab
        for component in relative.parts:
            path = path / component
            if path.is_symlink():
                raise ValueError(f"symlink is forbidden in a static binding path: {relative}")
        if binding["bytes"] > MAX_STATIC_BINDING_BYTES:
            raise ValueError(f"static preflight binding exceeds the text-artifact size limit: {relative}")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size != binding["bytes"]:
                raise ValueError(f"static preflight binding size/type changed: {relative}")
            payload = stream.read(MAX_STATIC_BINDING_BYTES + 1)
            after = os.fstat(stream.fileno())
            before_signature = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            after_signature = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            if before_signature != after_signature or len(payload) != before.st_size:
                raise ValueError(f"static preflight binding changed while being read: {relative}")
        if hashlib.sha256(payload).hexdigest() != binding["sha256"]:
            raise ValueError(f"static preflight binding hash changed: {relative}")
        payloads[relative.as_posix()] = payload

    recipe_key = str(RECIPE_REL)
    recipe = json.loads(payloads[recipe_key].decode("utf-8"))
    attempt = recipe.get("prospective_attempt", {})
    alignment = attempt.get("alignment", {})
    source = recipe.get("source_identity", {})
    authority = recipe.get("execution_authority", {})
    historical = recipe.get("historical_attempt", {})
    if not (
        recipe.get("schema") == "core.material.f4.supportcap_r002_static_temporal_alignment_design.v3"
        and recipe.get("record_id") == "f4-supportcap-affine-query-bound-v3-r002-static-design-v3"
        and attempt.get("attempt_id") == ATTEMPT_ID
        and attempt.get("candidate_id") == "f4_supportcap_affine_query_bound_v3"
        and attempt.get("q") == 0.5
        and attempt.get("dp_m") == 0.0075
        and attempt.get("denominator") == 512
        and attempt.get("substeps") == 2
        and attempt.get("support_cap") == 32
        and attempt.get("fresh_output_namespace") == str(ATTEMPT_REL / "trace.h5")
        and alignment.get("initial_native_frame") == FRAME_START
        and alignment.get("last_native_frame_inclusive") == FRAME_STOP
        and alignment.get("target_transition") == [40, 41]
        and alignment.get("advect_initial_seeds_before_target_transition") is True
        and alignment.get("query_original_t0_seed_positions_at_row40") is False
        and attempt.get("all_gates_and_event_censoring_unchanged") is True
        and source.get("path") == str(SOURCE_REL)
        and source.get("sha256") == SOURCE_SHA256
        and historical.get("attempt_id") == ATTEMPT_ID.replace("r002", "r001")
        and historical.get("modified") is False
        and historical.get("retried") is False
        and authority.get("cpu_canary_authorized") is False
        and authority.get("native_preflight_authorized") is False
        and authority.get("solver_authorized") is False
        and authority.get("gpu_authorized") is False
        and authority.get("worker_or_queue_authorized") is False
        and authority.get("qualification_credit") == 0
    ):
        raise ValueError("r002 static recipe no longer matches the exact preflight scope")


def read_authorization(path: Path = AUTHORIZATION, *, lab: Path = LAB) -> tuple[dict[str, Any], dict[str, Any]]:
    path = Path(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_STATIC_BINDING_BYTES:
            raise ValueError("F4 r002 authorization must be a bounded regular text file")
        payload = stream.read(MAX_STATIC_BINDING_BYTES + 1)
        after = os.fstat(stream.fileno())
        signature_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        signature_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        if signature_before != signature_after or len(payload) != before.st_size:
            raise ValueError("F4 r002 authorization changed while being read")
    authorization = json.loads(payload)
    binding = {
        "path": str(path.relative_to(lab)),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    return authorization, binding


def _mem_available_bytes() -> int:
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    raise RuntimeError("/proc/meminfo has no MemAvailable")


def _active_f3_material_workers() -> list[int]:
    workers: list[int] = []
    proc = Path("/proc")
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            command = (entry / "cmdline").read_bytes().replace(b"\0", b" ")
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if b"scripts/f3_native_volume_mls.py" in command:
            workers.append(int(entry.name))
    return sorted(workers)


def environment_preflight(*, lab: Path = LAB) -> dict[str, Any]:
    if any(os.environ.get(name) != "1" for name in _THREAD_ENV):
        raise RuntimeError("CPU thread limits must be configured before preflight")
    if os.environ.get("CUDA_VISIBLE_DEVICES", ""):
        raise RuntimeError("GPU visibility must be empty for the CPU-only preflight")
    import h5py
    import numpy as np

    cpus = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1)
    load = list(os.getloadavg())
    ram = _mem_available_bytes()
    disk = shutil.disk_usage(lab).free
    workers = _active_f3_material_workers()
    return {
        "schema": "core.material.f4.supportcap_affine_query_bound.r002_cpu_canary_environment_preflight.v1",
        "created_at_utc": stamp(),
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "h5py": h5py.__version__,
        "environment": {
            "thread_limits": {name: os.environ.get(name) for name in _THREAD_ENV},
            "thread_environment_original": _THREAD_ENV_ORIGINAL,
            "CUDA_VISIBLE_DEVICES": os.environ.get("CUDA_VISIBLE_DEVICES", ""),
            "CUDA_VISIBLE_DEVICES_original": _CUDA_VISIBLE_ORIGINAL,
        },
        "resources": {
            "available_cpu_count": cpus,
            "load_average_1_5_15_min": load,
            "available_ram_bytes": ram,
            "minimum_ram_bytes": MIN_RAM_BYTES,
            "filesystem_free_bytes": disk,
            "minimum_filesystem_free_bytes": MIN_DISK_BYTES,
            "cpu_workers": 1,
            "active_f3_material_worker_pids": workers,
        },
        "controls": {
            "preflight_only": True,
            "tracer_started": False,
            "solver_started": False,
            "gpu_initialized": False,
            "queue_or_scheduler_started": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
        },
    }


def resource_blockers(environment: dict[str, Any]) -> list[str]:
    resources = environment["resources"]
    blockers: list[str] = []
    if resources["load_average_1_5_15_min"][0] > resources["available_cpu_count"]:
        blockers.append("one-minute load average exceeds the CPUs available to this task")
    if resources["available_ram_bytes"] < MIN_RAM_BYTES:
        blockers.append("available RAM is below the 16 GiB preflight floor")
    if resources["filesystem_free_bytes"] < MIN_DISK_BYTES:
        blockers.append("free filesystem capacity is below the 8 GiB preflight floor")
    if resources["active_f3_material_worker_pids"]:
        blockers.append("the authorized F3 material worker is still active; avoid resource competition")
    return blockers


def input_preflight(
    authorization: dict[str, Any], *, source: Path = SOURCE,
) -> dict[str, Any]:
    if any(os.environ.get(name) != "1" for name in _THREAD_ENV):
        raise RuntimeError("CPU thread limits must be configured before reading native metadata")
    if os.environ.get("CUDA_VISIBLE_DEVICES", ""):
        raise RuntimeError("GPU visibility must be empty for the CPU-only preflight")
    import h5py
    import numpy as np

    source_contract = authorization["preflight_contract"]["source"]
    source = Path(source)
    descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("F4 r002 source is not a regular file")
        observed_bytes = metadata.st_size
        if observed_bytes != SOURCE_BYTES or observed_bytes != source_contract["bytes"]:
            raise ValueError("F4 r002 source byte length differs from the inherited static identity")
        source_signature = (
            metadata.st_dev, metadata.st_ino, metadata.st_size,
            metadata.st_mtime_ns, metadata.st_ctime_ns,
        )
        observed_sha = _sha256_stream(stream)
        after_hash = os.fstat(stream.fileno())
        if source_signature != (
            after_hash.st_dev, after_hash.st_ino, after_hash.st_size,
            after_hash.st_mtime_ns, after_hash.st_ctime_ns,
        ):
            raise ValueError("F4 r002 source changed during hash verification")
        if observed_sha != SOURCE_SHA256 or observed_sha != source_contract["sha256"]:
            raise ValueError("F4 r002 source SHA256 mismatch before any HDF5 open")
        required = {"time", "position", "velocity", "valid", "particle_zone"}
        # Hash and HDF5 access use one already-open no-follow file descriptor.
        with h5py.File(stream, "r") as handle:
            missing = sorted(required - set(handle))
            if missing:
                raise ValueError(f"F4 source lacks required datasets: {missing}")
            frames, particles = source_contract["frame_count"], source_contract["particle_count"]
            shape_ok = (
                handle["position"].shape == handle["velocity"].shape == (frames, particles, 3)
                and handle["valid"].shape == (frames, particles)
                and handle["particle_zone"].shape == (particles,)
            )
            times = np.asarray(handle["time"][FRAME_START : FRAME_STOP + 1], dtype=np.float64)
            time_ok = times.shape == (42,) and np.isfinite(times).all() and np.all(np.diff(times) > 0)
            if not (shape_ok and time_ok):
                raise ValueError("source layout or native time window differs from the r002 design")
        after_hdf5 = os.fstat(stream.fileno())
        if source_signature != (
            after_hdf5.st_dev, after_hdf5.st_ino, after_hdf5.st_size,
            after_hdf5.st_mtime_ns, after_hdf5.st_ctime_ns,
        ):
            raise ValueError("F4 r002 source changed during read-only metadata validation")
    return {
        "schema": "core.material.f4.supportcap_affine_query_bound.r002_cpu_canary_input_preflight.v1",
        "created_at_utc": stamp(),
        "source": {
            "path": str(source.relative_to(LAB)),
            "bytes": observed_bytes,
            "sha256": observed_sha,
            "read_only": True,
        },
        "source_hdf5_opened_after_hash_match": True,
        "native_window": {
            "first_row": FRAME_START,
            "last_row_inclusive": FRAME_STOP,
            "expected_saved_rows": FRAME_STOP + 1,
            "times_strictly_increasing": True,
            "time_start_s": float(times[0]),
            "time_end_s": float(times[-1]),
        },
        "tracer_started": False,
        "qualification_credit": 0,
    }


def _fsync_directory(path: Path) -> None:
    directory_fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _write_exclusive(path: Path, value: dict[str, Any]) -> None:
    payload = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    _fsync_directory(path.parent)


def _finalize_receipt(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".partial")
    _write_exclusive(temporary, value)
    os.replace(temporary, path)
    _fsync_directory(path.parent)


def run_preflight(
    authorization: dict[str, Any],
    *,
    scope_dir: Path = SCOPE_DIR,
    output_dir: Path = OUTPUT_DIR,
    lab: Path = LAB,
    authorization_binding: dict[str, Any] | None = None,
    resource_probe: Callable[[], dict[str, Any]] = environment_preflight,
    source_probe: Callable[[dict[str, Any]], dict[str, Any]] = input_preflight,
) -> dict[str, Any]:
    validate_authorization(authorization)
    validate_static_bindings(authorization, lab=lab)
    if authorization_binding is None:
        payload = json.dumps(authorization, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        authorization_binding = {
            "path": None,
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "encoding": "canonical-json-test-orchestrator-input",
        }
    if not (
        isinstance(authorization_binding.get("bytes"), int)
        and authorization_binding["bytes"] > 0
        and isinstance(authorization_binding.get("sha256"), str)
        and len(authorization_binding["sha256"]) == 64
    ):
        raise ValueError("preflight authorization binding is malformed")
    scope_dir = Path(scope_dir)
    receipt_path = scope_dir / "preflight-receipt.json"
    if receipt_path.exists() or receipt_path.is_symlink():
        raise FileExistsError("the one authorized F4 r002 preflight was already consumed; no retry")
    if output_dir.exists() or output_dir.is_symlink():
        raise FileExistsError("r002 canary output namespace exists; preflight cannot authorize reuse")

    started = {
        "schema": SCHEMA,
        "record_id": ATTEMPT_ID + "-cpu-canary-preflight-r002-v1",
        "started_at_utc": stamp(),
        "status": "preflight_started_no_runtime_authorization",
        "preflight_only": True,
        "runtime_execution_authorized": False,
        "retry_allowed": False,
        "terminal_receipt_pending": True,
        "authorization_binding": authorization_binding,
    }
    # The exclusive start record itself consumes the single preflight. If a
    # later write fails, it remains as a durable non-success state and blocks
    # retries instead of leaving no evidence that the attempt began.
    _write_exclusive(receipt_path, started)
    environment: dict[str, Any] | None = None
    inputs: dict[str, Any] | None = None
    blockers: list[str] = []
    status = "preflight_failed_no_runtime_authorization"
    failure: str | None = None
    try:
        environment = resource_probe()
        blockers = resource_blockers(environment)
        if blockers:
            status = "preflight_deferred_resource_gate_no_runtime_authorization"
        else:
            inputs = source_probe(authorization)
            status = "preflight_passed_runtime_not_authorized"
    except Exception as error:
        failure = f"{type(error).__name__}: {error}"

    receipt = {
        "schema": SCHEMA,
        "record_id": ATTEMPT_ID + "-cpu-canary-preflight-r002-v1",
        "created_at_utc": stamp(),
        "status": status,
        "scope": {
            "attempt_id": ATTEMPT_ID,
            "native_rows_inclusive": [FRAME_START, FRAME_STOP],
            "candidate_id": "f4_supportcap_affine_query_bound_v3",
            "preflight_only": True,
            "runtime_execution_authorized": False,
            "same_input_retry_allowed": False,
        },
        "authorization_binding": authorization_binding,
        "environment_preflight": environment,
        "input_preflight": inputs,
        "resource_blockers": blockers,
        "failure": failure,
        "execution_controls": {
            "canary_started": False,
            "tracer_started": False,
            "solver_started": False,
            "gpu_initialized": False,
            "queue_or_scheduler_started": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "qualification_credit": 0,
        },
        "retry_policy": {"preflight_attempts": 1, "same_scope_retry_allowed": False},
    }
    _finalize_receipt(receipt_path, receipt)
    return receipt


def main() -> int:
    configure_cpu_preflight_environment()
    authorization, authorization_binding = read_authorization()
    receipt = run_preflight(authorization, authorization_binding=authorization_binding)
    print(json.dumps({"status": receipt["status"], "canary_started": False}, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
