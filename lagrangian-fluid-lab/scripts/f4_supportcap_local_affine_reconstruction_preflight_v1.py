"""Consume one F4 v4 CPU/native input-and-environment preflight only.

This tool verifies frozen static bindings, CPU resource floors, the identity
of the existing F4 native HDF5, and the presence/shape/time axis of rows 0-41.
It never loads native particle frames or runs candidate code, a tracer, solver,
GPU, worker, scheduler, queue, registry, or ledger operation. Passing grants
no runtime permission.
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


LAB = Path(__file__).resolve().parents[1]
CANDIDATE_ID = "f4_supportcap_local_affine_reconstruction_v4"
ATTEMPT_ID = "f4-supportcap-local-affine-reconstruction-v4-cpu-native-canary-r001"
CANDIDATE_REL = Path("campaigns/core-v1/material/candidates/f4-supportcap-local-affine-reconstruction-v4")
SCOPE_REL = CANDIDATE_REL / "cpu-native-preflight-v1"
SCOPE_DIR = LAB / SCOPE_REL
AUTHORIZATION = SCOPE_DIR / "authorization.json"
LOCK = SCOPE_DIR / "one-shot-lock.json"
RECEIPT = SCOPE_DIR / "preflight-receipt.json"
SOURCE_REL = Path(
    "campaigns/core-v1/cfd/f4-tallwall120-archives-v2/"
    "f4-tallwall120-qualification-cell-14/product/trajectory.h5"
)
SOURCE = LAB / SOURCE_REL
CANARY_NAMESPACE_REL = Path("campaigns/core-v1/material/evidence") / ATTEMPT_ID
CANARY_NAMESPACE = LAB / CANARY_NAMESPACE_REL
SOURCE_SHA256 = "91846866c177e4c3036b7ef92c33a4e0bde7d9e8993efb01dde300811b7c096e"
SOURCE_BYTES = 10_326_356_548
SOURCE_FRAMES = 1086
SOURCE_PARTICLES = 217_485
FRAME_START = 0
FRAME_STOP = 41
MIN_RAM_BYTES = 16 * 1024**3
MIN_DISK_BYTES = 8 * 1024**3
MAX_STATIC_BINDING_BYTES = 2 * 1024**2
THREAD_ENV = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")
AUTH_SCHEMA = "core.material.f4.supportcap.local_affine_reconstruction.cpu_native_preflight_authorization.v1"
RECEIPT_SCHEMA = "core.material.f4.supportcap.local_affine_reconstruction.cpu_native_preflight.v1"
REQUIRED_STATIC_BINDINGS = {
    str(CANDIDATE_REL / "candidate-card-v1.json"),
    "scripts/core_material.py",
    "scripts/f4_tallwall120_material.py",
    "scripts/f4_supportcap_affine_query_bound_candidate_v3.py",
    "scripts/f4_supportcap_affine_reconstruction_candidate_v4.py",
    "scripts/f3_material_neighbors.py",
    "scripts/passive_tracers.py",
    "scripts/f4_supportcap_affine_reconstruction_calibration_v1.py",
    "scripts/f4_material_calibration.py",
    "scripts/f4_material_calibration_v3.py",
    "scripts/f4_supportcap_local_affine_reconstruction_preflight_v1.py",
    "tests/test_f4_supportcap_affine_reconstruction_candidate_v4.py",
    "tests/test_f4_supportcap_local_affine_reconstruction_preflight_v1.py",
    "campaigns/core-v1/material/evidence/f4-supportcap-local-affine-reconstruction-v4-synthetic-calibration-v1.json",
    "campaigns/core-v1/material/evidence/f4-supportcap-affine-query-bound-v3-cpu-native-canary-r001-failure-attribution-v1.json",
    "campaigns/core-v1/material/candidates/f4-supportcap-affine-query-bound-v3/r002-static-design-v3/recipe.json",
}


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_stream(stream) -> str:
    digest = hashlib.sha256()
    stream.seek(0)
    for chunk in iter(lambda: stream.read(8 << 20), b""):
        digest.update(chunk)
    stream.seek(0)
    return digest.hexdigest()


def _read_bounded_nofollow(path: Path, *, max_bytes: int) -> tuple[bytes, os.stat_result]:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > max_bytes:
            raise ValueError(f"expected a bounded regular file: {path}")
        payload = stream.read(max_bytes + 1)
        after = os.fstat(stream.fileno())
        signature = lambda value: (
            value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns
        )
        if signature(before) != signature(after) or len(payload) != before.st_size:
            raise ValueError(f"file changed while being read: {path}")
    return payload, before


def read_authorization(path: Path = AUTHORIZATION, *, lab: Path = LAB) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, _ = _read_bounded_nofollow(Path(path), max_bytes=MAX_STATIC_BINDING_BYTES)
    value = json.loads(payload.decode("utf-8"))
    return value, {
        "path": str(Path(path).relative_to(lab)),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def validate_authorization(value: dict[str, Any]) -> None:
    authorization = value.get("authorization", {})
    contract = value.get("preflight_contract", {})
    source = contract.get("source", {})
    controls = value.get("execution_controls", {})
    if value.get("schema") != AUTH_SCHEMA or value.get("status") != "authorized_preflight_only_runtime_not_authorized":
        raise ValueError("missing or unexpected F4 v4 CPU/native preflight authorization")
    expected_scope = {
        "authority": "explicit user authorization: one F4 new-candidate CPU/native canary preflight",
        "candidate_id": CANDIDATE_ID,
        "attempt_id": ATTEMPT_ID,
        "preflight_attempts": 1,
        "same_scope_retry_allowed": False,
        "runtime_execution_authorized": False,
        "native_rows_inclusive": [FRAME_START, FRAME_STOP],
    }
    for key, expected in expected_scope.items():
        if authorization.get(key) != expected:
            raise ValueError(f"preflight authorization scope mismatch: {key}")
    if not (
        contract.get("source_path") == str(SOURCE_REL)
        and contract.get("source_bytes") == SOURCE_BYTES
        and contract.get("source_sha256") == SOURCE_SHA256
        and contract.get("source_frame_count") == SOURCE_FRAMES
        and contract.get("source_particle_count") == SOURCE_PARTICLES
        and contract.get("native_rows_inclusive") == [FRAME_START, FRAME_STOP]
        and contract.get("candidate_card_path") == str(CANDIDATE_REL / "candidate-card-v1.json")
        and contract.get("seed_denominator") == 512
        and contract.get("q") == 0.5
        and contract.get("dp_m") == 0.0075
        and contract.get("substeps_if_later_authorized") == 2
        and source.get("path") == str(SOURCE_REL)
        and source.get("bytes") == SOURCE_BYTES
        and source.get("sha256") == SOURCE_SHA256
        and source.get("frame_count") == SOURCE_FRAMES
        and source.get("particle_count") == SOURCE_PARTICLES
        and contract.get("minimum_ram_bytes") == MIN_RAM_BYTES
        and contract.get("minimum_disk_bytes") == MIN_DISK_BYTES
        and contract.get("max_static_binding_bytes") == MAX_STATIC_BINDING_BYTES
        and controls.get("candidate_executed") is False
        and controls.get("native_particle_frames_loaded") is False
        and controls.get("tracer_started") is False
        and controls.get("canary_started") is False
        and controls.get("solver_started") is False
        and controls.get("gpu_initialized") is False
        and controls.get("worker_or_queue_started") is False
        and controls.get("t2_started") is False
        and controls.get("registry_mutation") == 0
        and controls.get("ledger_mutation") == 0
    ):
        raise ValueError("preflight contract does not bind the authorized CPU/native-only scope")
    bindings = value.get("static_bindings", [])
    by_path = {entry.get("path"): entry for entry in bindings}
    if len(by_path) != len(bindings) or not REQUIRED_STATIC_BINDINGS.issubset(by_path):
        raise ValueError("preflight authorization lacks required unique static bindings")


def validate_static_bindings(value: dict[str, Any], *, lab: Path = LAB) -> None:
    validate_authorization(value)
    payloads: dict[str, bytes] = {}
    for binding in value["static_bindings"]:
        relative = Path(binding["path"])
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or relative.suffix.lower() not in {".json", ".py", ".md", ".txt"}
            or not isinstance(binding.get("bytes"), int)
            or not isinstance(binding.get("sha256"), str)
            or len(binding["sha256"]) != 64
            or not 0 < binding["bytes"] <= MAX_STATIC_BINDING_BYTES
        ):
            raise ValueError(f"invalid static binding: {relative}")
        path = lab
        for component in relative.parts:
            path = path / component
            if path.is_symlink():
                raise ValueError(f"symlinks are forbidden in static binding paths: {relative}")
        payload, before = _read_bounded_nofollow(path, max_bytes=MAX_STATIC_BINDING_BYTES)
        if len(payload) != binding["bytes"] or hashlib.sha256(payload).hexdigest() != binding["sha256"]:
            raise ValueError(f"static binding digest or size mismatch: {relative}")
        payloads[relative.as_posix()] = payload

    by_path = {entry["path"]: entry for entry in value["static_bindings"]}
    card_path = value["preflight_contract"]["candidate_card_path"]
    card = json.loads(payloads[card_path].decode("utf-8"))
    if not (
        card.get("candidate_id") == CANDIDATE_ID
        and card.get("status") == "proposal_only_cpu_native_preflight_authorized_runtime_not_authorized"
        and card.get("production_tracer_registered") is False
        and card.get("qualification_claim") == "none"
        and card.get("credit") == 0
        and card.get("preflight_scope", {}).get("attempt_id") == ATTEMPT_ID
        and card.get("preflight_scope", {}).get("actual_canary_authorized") is False
    ):
        raise ValueError("candidate card is not the exact preflight-only candidate contract")
    for card_binding in card.get("input_bindings", {}).values():
        authorization_binding = by_path.get(card_binding.get("path"))
        if authorization_binding is None or (
            authorization_binding.get("sha256") != card_binding.get("sha256")
            or authorization_binding.get("bytes") != card_binding.get("bytes")
        ):
            raise ValueError("preflight authorization does not close every candidate-card binding")
    recipe_path = "campaigns/core-v1/material/candidates/f4-supportcap-affine-query-bound-v3/r002-static-design-v3/recipe.json"
    recipe = json.loads(payloads[recipe_path].decode("utf-8"))
    alignment = recipe.get("prospective_attempt", {}).get("alignment", {})
    if not (
        alignment.get("initial_native_frame") == 0
        and alignment.get("last_native_frame_inclusive") == FRAME_STOP
        and alignment.get("target_transition") == [40, 41]
        and alignment.get("advect_initial_seeds_before_target_transition") is True
        and alignment.get("query_original_t0_seed_positions_at_row40") is False
    ):
        raise ValueError("bound temporal-alignment recipe does not fix the R001 stale-seed setup")
    result_path = "campaigns/core-v1/material/evidence/f4-supportcap-local-affine-reconstruction-v4-synthetic-calibration-v1.json"
    result = json.loads(payloads[result_path].decode("utf-8"))
    if not (
        result.get("candidate_id") == CANDIDATE_ID
        and result.get("summary", {}).get("total_queries") == 5632
        and result.get("summary", {}).get("v3_gate_pass_count") == 5632
        and result.get("summary", {}).get("v4_gate_pass_count") == 5632
        and result.get("interpretation", {}).get("native_or_event_validation") is False
        and result.get("interpretation", {}).get("qualification_claim") == "none"
        and result.get("interpretation", {}).get("credit") == 0
    ):
        raise ValueError("synthetic calibration does not match the candidate card contract")


def configure_cpu_preflight_environment() -> dict[str, Any]:
    original_threads = {name: os.environ.get(name) for name in THREAD_ENV}
    original_cuda = os.environ.get("CUDA_VISIBLE_DEVICES")
    for name in THREAD_ENV:
        os.environ[name] = "1"
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    return {"thread_environment_original": original_threads, "CUDA_VISIBLE_DEVICES_original": original_cuda}


def _mem_available_bytes() -> int:
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    raise RuntimeError("/proc/meminfo has no MemAvailable field")


def _active_material_workers() -> list[int]:
    workers: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            command = (entry / "cmdline").read_bytes().replace(b"\0", b" ")
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if any(
            marker in command
            for marker in (
                b"scripts/f3_native_volume_mls.py",
                b"scripts/f4_tallwall120_material.py",
                b"scripts/f4_supportcap_affine_query_bound_cpu_canary_execute_v1.py",
            )
        ):
            workers.append(int(entry.name))
    return sorted(workers)


def environment_preflight(*, lab: Path = LAB, original_environment: dict[str, Any] | None = None) -> dict[str, Any]:
    if any(os.environ.get(name) != "1" for name in THREAD_ENV) or os.environ.get("CUDA_VISIBLE_DEVICES", ""):
        raise RuntimeError("CPU-only thread limits and hidden CUDA devices are required")
    import h5py
    import numpy as np
    import scipy

    cpus = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1)
    return {
        "created_at_utc": stamp(),
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "h5py": h5py.__version__,
        "environment": {
            "thread_limits": {name: os.environ.get(name) for name in THREAD_ENV},
            "original": original_environment,
            "CUDA_VISIBLE_DEVICES": os.environ.get("CUDA_VISIBLE_DEVICES", ""),
        },
        "resources": {
            "available_cpu_count": cpus,
            "load_average_1_5_15_min": list(os.getloadavg()),
            "available_ram_bytes": _mem_available_bytes(),
            "minimum_ram_bytes": MIN_RAM_BYTES,
            "filesystem_free_bytes": shutil.disk_usage(lab).free,
            "minimum_filesystem_free_bytes": MIN_DISK_BYTES,
            "cpu_workers": 1,
            "active_material_worker_pids": _active_material_workers(),
        },
        "controls": {
            "preflight_only": True,
            "candidate_executed": False,
            "native_particle_frames_loaded": False,
            "tracer_started": False,
            "canary_started": False,
            "solver_started": False,
            "gpu_initialized": False,
            "worker_or_queue_started": False,
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
    if resources["active_material_worker_pids"]:
        blockers.append("an F3/F4 material worker is active; avoid resource competition")
    return blockers


def input_preflight(authorization: dict[str, Any], *, source: Path = SOURCE, lab: Path = LAB) -> dict[str, Any]:
    if any(os.environ.get(name) != "1" for name in THREAD_ENV) or os.environ.get("CUDA_VISIBLE_DEVICES", ""):
        raise RuntimeError("CPU-only thread limits and hidden CUDA devices are required before source access")
    import h5py
    import numpy as np

    preflight_contract = authorization["preflight_contract"]
    contract = preflight_contract["source"]
    frame_start, frame_stop = preflight_contract.get("native_rows_inclusive", [FRAME_START, FRAME_STOP])
    if (
        isinstance(frame_start, bool)
        or isinstance(frame_stop, bool)
        or not isinstance(frame_start, int)
        or not isinstance(frame_stop, int)
        or frame_start < 0
        or frame_stop < frame_start
    ):
        raise ValueError("invalid native row interval in the preflight contract")
    source = Path(source)
    source_descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(source_descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("authorized F4 source is not a regular file")
        if before.st_size != contract["bytes"]:
            raise ValueError("F4 source byte length differs from the frozen identity")
        signature = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        source_sha = _sha256_stream(stream)
        after_hash = os.fstat(stream.fileno())
        if signature != (after_hash.st_dev, after_hash.st_ino, after_hash.st_size, after_hash.st_mtime_ns, after_hash.st_ctime_ns):
            raise ValueError("F4 source changed during SHA-256 verification")
        if source_sha != contract["sha256"]:
            raise ValueError("F4 source SHA-256 differs from the frozen identity")
        with h5py.File(stream, "r") as handle:
            required = {"time", "position", "velocity", "valid", "particle_zone"}
            missing = sorted(required - set(handle))
            if missing:
                raise ValueError(f"F4 source lacks required datasets: {missing}")
            frames = contract["frame_count"]
            particles = contract["particle_count"]
            shapes_ok = (
                handle["position"].shape == handle["velocity"].shape == (frames, particles, 3)
                and handle["valid"].shape == (frames, particles)
                and handle["particle_zone"].shape == (particles,)
                and handle["time"].shape == (frames,)
            )
            times = np.asarray(handle["time"][frame_start : frame_stop + 1], dtype=np.float64)
            time_ok = times.shape == (frame_stop - frame_start + 1,) and np.isfinite(times).all() and np.all(np.diff(times) > 0)
            if not (shapes_ok and time_ok):
                raise ValueError("F4 source dataset layout or native row-0-to-41 time axis differs from frozen contract")
        after_hdf5 = os.fstat(stream.fileno())
        if signature != (after_hdf5.st_dev, after_hdf5.st_ino, after_hdf5.st_size, after_hdf5.st_mtime_ns, after_hdf5.st_ctime_ns):
            raise ValueError("F4 source changed during read-only HDF5 metadata validation")
    return {
        "created_at_utc": stamp(),
        "source": {"path": str(source.relative_to(lab)), "bytes": before.st_size, "sha256": source_sha, "read_only": True},
        "source_hdf5_opened_after_hash_match": True,
        "datasets_and_shapes_validated": True,
        "native_window": {
            "first_row": frame_start,
            "last_row_inclusive": frame_stop,
            "saved_rows": len(times),
            "time_start_s": float(times[0]),
            "time_end_s": float(times[-1]),
            "times_strictly_increasing": True,
        },
        "native_particle_frames_loaded": False,
        "candidate_executed": False,
        "qualification_credit": 0,
    }


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


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
    canary_namespace: Path = CANARY_NAMESPACE,
    lab: Path = LAB,
    authorization_binding: dict[str, Any] | None = None,
    original_environment: dict[str, Any] | None = None,
    resource_probe: Callable[[], dict[str, Any]] | None = None,
    source_probe: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    validate_static_bindings(authorization, lab=lab)
    if authorization_binding is None:
        canonical = json.dumps(authorization, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        authorization_binding = {"path": None, "bytes": len(canonical), "sha256": hashlib.sha256(canonical).hexdigest()}
    if not (
        isinstance(authorization_binding.get("bytes"), int)
        and authorization_binding["bytes"] > 0
        and isinstance(authorization_binding.get("sha256"), str)
        and len(authorization_binding["sha256"]) == 64
    ):
        raise ValueError("authorization digest binding is malformed")

    scope_dir = Path(scope_dir)
    lock_path = scope_dir / "one-shot-lock.json"
    receipt_path = scope_dir / "preflight-receipt.json"
    if lock_path.exists() or lock_path.is_symlink() or receipt_path.exists() or receipt_path.is_symlink():
        raise FileExistsError("the authorized F4 v4 CPU/native preflight was already consumed; no retry")
    if Path(canary_namespace).exists() or Path(canary_namespace).is_symlink():
        raise FileExistsError("the separate future canary namespace is not empty; no reuse is allowed")

    started = {
        "schema": RECEIPT_SCHEMA,
        "record_id": ATTEMPT_ID + "-cpu-native-preflight-v1",
        "started_at_utc": stamp(),
        "status": "preflight_started_no_runtime_authorization",
        "preflight_only": True,
        "runtime_execution_authorized": False,
        "same_scope_retry_allowed": False,
        "authorization_binding": authorization_binding,
    }
    # The durable exclusive lock consumes the only authorized preflight.
    _write_exclusive(lock_path, started)

    environment: dict[str, Any] | None = None
    inputs: dict[str, Any] | None = None
    blockers: list[str] = []
    failure: str | None = None
    status = "preflight_failed_runtime_not_authorized"
    try:
        if resource_probe is None:
            resource_probe = lambda: environment_preflight(lab=lab, original_environment=original_environment)
        if source_probe is None:
            source_probe = lambda auth: input_preflight(auth, lab=lab)
        environment = resource_probe()
        blockers = resource_blockers(environment)
        if blockers:
            status = "preflight_deferred_resource_gate_runtime_not_authorized"
        else:
            inputs = source_probe(authorization)
            status = "preflight_passed_runtime_not_authorized"
    except Exception as error:  # a terminal receipt preserves the consumed one-shot
        failure = f"{type(error).__name__}: {error}"

    receipt = {
        "schema": RECEIPT_SCHEMA,
        "record_id": ATTEMPT_ID + "-cpu-native-preflight-v1",
        "created_at_utc": stamp(),
        "status": status,
        "scope": {
            "attempt_id": ATTEMPT_ID,
            "candidate_id": CANDIDATE_ID,
            "native_rows_inclusive": [FRAME_START, FRAME_STOP],
            "preflight_only": True,
            "runtime_execution_authorized": False,
            "same_scope_retry_allowed": False,
        },
        "authorization_binding": authorization_binding,
        "environment_preflight": environment,
        "input_preflight": inputs,
        "resource_blockers": blockers,
        "failure": failure,
        "execution_controls": {
            "candidate_executed": False,
            "native_particle_frames_loaded": False,
            "canary_started": False,
            "tracer_started": False,
            "solver_started": False,
            "gpu_initialized": False,
            "worker_or_queue_started": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "T2_started": False,
            "qualification_credit": 0,
        },
        "retry_policy": {"preflight_attempts": 1, "same_scope_retry_allowed": False},
    }
    _finalize_receipt(receipt_path, receipt)
    return receipt


def main() -> int:
    original = configure_cpu_preflight_environment()
    authorization, binding = read_authorization()
    receipt = run_preflight(authorization, authorization_binding=binding, original_environment=original)
    print(json.dumps({"status": receipt["status"], "canary_started": False}, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
