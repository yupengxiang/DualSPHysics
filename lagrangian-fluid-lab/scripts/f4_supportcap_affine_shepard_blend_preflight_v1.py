"""One-shot F4 v5 CPU/native input-and-environment preflight only.

This tool never executes the predictor, loads native particle arrays, starts a
tracer/solver/worker/GPU/queue, or grants runtime authorization. A resource-only
deferral before the durable start lock does not consume the one-shot.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
from datetime import datetime, timezone
from typing import Any

LAB = Path(__file__).resolve().parents[1]
CANDIDATE_ID = "f4_supportcap_affine_shepard_blend_v5"
ATTEMPT_ID = "f4-supportcap-affine-shepard-blend-v5-cpu-native-canary-r001"
CANDIDATE_REL = Path("campaigns/core-v1/material/candidates/f4-supportcap-affine-shepard-blend-v5")
SCOPE_REL = CANDIDATE_REL / "cpu-native-preflight-v1"
SCOPE_DIR = LAB / SCOPE_REL
CARD_REL = CANDIDATE_REL / "candidate-card-v1.json"
CARD_PATH = LAB / CARD_REL
AUTH_REL = SCOPE_REL / "authorization.json"
AUTH_PATH = LAB / AUTH_REL
LOCK_NAME = "one-shot-lock.json"
RECEIPT_NAME = "preflight-receipt.json"
OUTPUT_REL = Path("campaigns/core-v1/material/evidence") / ATTEMPT_ID
OUTPUT_NAMESPACE = LAB / OUTPUT_REL
STATE_DIR = Path("/home/jade/.local")
ONE_SHOT_MARKER_NAME = "f4_supportcap_affine_shepard_blend_v5_cpu_native_preflight_v1.consumed.json"
ONE_SHOT_MARKER_LABEL = "per-user-private-state/" + ONE_SHOT_MARKER_NAME
SOURCE_REL = Path(
    "campaigns/core-v1/cfd/f4-tallwall120-archives-v2/"
    "f4-tallwall120-qualification-cell-14/product/trajectory.h5"
)
SOURCE_PATH = LAB / SOURCE_REL
SOURCE_IDENTITY = {
    "path": SOURCE_REL.as_posix(),
    "bytes": 10_326_356_548,
    "sha256": "91846866c177e4c3036b7ef92c33a4e0bde7d9e8993efb01dde300811b7c096e",
    "frame_count": 1086,
    "particle_count": 217_485,
}
NATIVE_ROWS = [0, 41]
SEED_DENOMINATOR = 512
Q = 0.5
DP_M = 0.0075
SUBSTEPS = 2
SUPPORT_CAP = 32
MIN_RAM_BYTES = 16 * 1024**3
MIN_DISK_BYTES = 8 * 1024**3
MAX_STATIC_BYTES = 2 * 1024**2
THREAD_ENV = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")
SCHEMA = "core.material.f4.supportcap_affine_shepard_blend.cpu_native_preflight.v1"
AUTH_SCHEMA = "core.material.f4.supportcap_affine_shepard_blend.cpu_native_preflight_authorization.v1"
CARD_SCHEMA = "core.material.f4.supportcap_affine_shepard_blend.candidate_card.v1"
# Trusted entrypoint anchor: preflight verifies this card before consulting its closure.
FROZEN_CARD_SHA256 = "25acdfb39c98cf64293454e51237d91bf1ea91217020d7e15a547cefedaca653"
SCRIPT_REL = Path("scripts/f4_supportcap_affine_shepard_blend_preflight_v1.py")
TEST_REL = Path("tests/test_f4_supportcap_affine_shepard_blend_preflight_v1.py")

CANDIDATE_INPUTS = {
    "candidate_implementation": Path("scripts/f4_supportcap_affine_shepard_blend_candidate_v5.py"),
    "candidate_tests": Path("tests/test_f4_supportcap_affine_shepard_blend_candidate_v5.py"),
    "baseline_v3": Path("scripts/f4_supportcap_affine_query_bound_candidate_v3.py"),
    "affine_v4_component": Path("scripts/f4_supportcap_affine_reconstruction_candidate_v4.py"),
    "core_material_and_gate": Path("scripts/core_material.py"),
    "visible_neighbor_search": Path("scripts/f3_material_neighbors.py"),
    "support_gate": Path("scripts/passive_tracers.py"),
    "native_material_reader": Path("scripts/f4_tallwall120_material.py"),
    "calibration_geometry": Path("scripts/f4_material_calibration.py"),
    "calibration_profile_v3": Path("scripts/f4_material_calibration_v3.py"),
    "blend_calibration_script": Path("scripts/f4_supportcap_affine_shepard_blend_calibration_v1.py"),
    "blend_calibration_receipt": Path("campaigns/core-v1/material/candidates/f4-supportcap-affine-shepard-blend-v5/synthetic-calibration-v1/receipt.json"),
    "heldout_script": Path("scripts/f4_supportcap_affine_shepard_blend_heldout_v2.py"),
    "heldout_tests": Path("tests/test_f4_supportcap_affine_shepard_blend_heldout_v2.py"),
    "heldout_design": Path("campaigns/core-v1/material/candidates/f4-supportcap-affine-shepard-blend-v5/synthetic-calibration-v1/heldout-design-v2-final.json"),
    "heldout_receipt": Path("campaigns/core-v1/material/candidates/f4-supportcap-affine-shepard-blend-v5/synthetic-calibration-v1/heldout-receipt-v2-final.json"),
    "terra_review_record": Path("reports/CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-217.zh-CN.md"),
    "candidate_code_review_record": Path("reports/CORE-CONTINUATION-STATUS-2026-09-27-UPDATE-218.zh-CN.md"),
    "historical_v4_candidate_card": Path("campaigns/core-v1/material/candidates/f4-supportcap-local-affine-reconstruction-v4/candidate-card-v1.json"),
    "historical_t1_source_receipt": Path("campaigns/core-v1/material/evidence/f4-tallwall120-native-cell14-material-preflight-20260921.json"),
    "historical_v4_preflight_code": Path("scripts/f4_supportcap_local_affine_reconstruction_preflight_v1.py"),
    "requirements": Path("requirements.txt"),
}

_ORIGINAL_ENVIRONMENT: dict[str, str | None] | None = None


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _reference(path: Path) -> dict[str, Any]:
    path = Path(path)
    absolute = LAB / path
    payload = _read_bounded(absolute)
    return {"path": path.as_posix(), "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def _decode_frozen_candidate_card(payload: bytes) -> dict[str, Any]:
    if hashlib.sha256(payload).hexdigest() != FROZEN_CARD_SHA256:
        raise ValueError("candidate card differs from the reviewed, code-pinned digest")
    card = json.loads(payload.decode("utf-8"))
    if not isinstance(card, dict):
        raise ValueError("candidate card must be a JSON object")
    if (
        card.get("schema") != CARD_SCHEMA
        or card.get("candidate_id") != CANDIDATE_ID
        or card.get("preflight_scope", {}).get("attempt_id") != ATTEMPT_ID
        or card.get("preflight_scope", {}).get("one_shot_marker") != ONE_SHOT_MARKER_LABEL
        or card.get("preflight_scope", {}).get("actual_canary_authorized") is not False
    ):
        raise ValueError("candidate card does not match the pinned v5 preflight scope")
    return card


def _open_absolute_directory(path: Path, *, create: bool = False) -> int:
    absolute = Path(path).absolute()
    if not absolute.is_absolute():
        raise ValueError("directory path must be absolute")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(absolute.anchor, flags)
    try:
        for component in absolute.parts[1:]:
            if component in {"", ".", ".."}:
                raise ValueError(f"unsafe directory component in {absolute}")
            try:
                child = os.open(component, flags, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(component, 0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
                child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _open_private_state_directory() -> int:
    descriptor = _open_absolute_directory(STATE_DIR)
    state = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(state.st_mode)
        or state.st_uid != os.getuid()
        or stat.S_IMODE(state.st_mode) & 0o077
    ):
        os.close(descriptor)
        raise PermissionError("one-shot state directory must be private and owned by the invoking user")
    return descriptor


def _require_path_matches_directory_fd(path: Path, directory_fd: int, label: str) -> None:
    path_fd = _open_absolute_directory(path)
    try:
        expected = os.fstat(directory_fd)
        actual = os.fstat(path_fd)
        if (expected.st_dev, expected.st_ino) != (actual.st_dev, actual.st_ino):
            raise RuntimeError(f"{label} path no longer names the pinned directory")
    finally:
        os.close(path_fd)


def _open_absolute_regular(path: Path, *, flags: int = os.O_RDONLY) -> int:
    absolute = Path(path).absolute()
    if absolute.name in {"", ".", ".."}:
        raise ValueError(f"invalid file path: {absolute}")
    parent = _open_absolute_directory(absolute.parent)
    try:
        return os.open(
            absolute.name,
            flags | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0),
            dir_fd=parent,
        )
    finally:
        os.close(parent)


def _read_bounded(path: Path, limit: int = MAX_STATIC_BYTES) -> bytes:
    descriptor = _open_absolute_regular(Path(path))
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise ValueError(f"expected bounded regular file: {path}")
        value = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
        signature = lambda row: (row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns, row.st_ctime_ns)
        if signature(before) != signature(after) or len(value) != before.st_size:
            raise ValueError(f"file changed while being read: {path}")
    return value


def build_authorization() -> dict[str, Any]:
    card_bytes = _read_bounded(CARD_PATH)
    card = _decode_frozen_candidate_card(card_bytes)
    input_bindings = card.get("input_bindings")
    if not isinstance(input_bindings, dict) or set(input_bindings) != set(CANDIDATE_INPUTS):
        raise ValueError("frozen candidate card has an incomplete input closure")
    paths = {binding["path"] for binding in input_bindings.values()}
    card_bindings_by_path = {binding["path"]: binding for binding in input_bindings.values()}
    paths.update({CARD_REL.as_posix(), SCRIPT_REL.as_posix(), TEST_REL.as_posix()})
    static_bindings = []
    for relative in sorted(paths):
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"invalid static binding path: {relative}")
        binding = _reference(path)
        if relative in card_bindings_by_path and binding != card_bindings_by_path[relative]:
            raise ValueError(f"candidate input differs from the pinned card: {relative}")
        static_bindings.append(binding)
    return {
        "schema": AUTH_SCHEMA,
        "status": "authorized_one_cpu_native_canary_preflight_runtime_not_authorized",
        "authority": "explicit user authorization: F4 supportcap one CPU/native canary preflight",
        "candidate_id": CANDIDATE_ID,
        "attempt_id": ATTEMPT_ID,
        "max_preflight_attempts": 1,
        "same_scope_retry_allowed": False,
        "runtime_execution_authorized": False,
        "preflight_contract": {
            "source": SOURCE_IDENTITY,
            "native_rows_inclusive": NATIVE_ROWS,
            "seed_denominator": SEED_DENOMINATOR,
            "q": Q,
            "dp_m": DP_M,
            "substeps_if_later_separately_authorized": SUBSTEPS,
            "support_cap": SUPPORT_CAP,
            "minimum_ram_bytes": MIN_RAM_BYTES,
            "minimum_disk_bytes": MIN_DISK_BYTES,
            "max_static_binding_bytes": MAX_STATIC_BYTES,
            "fresh_output_namespace": OUTPUT_REL.as_posix(),
            "one_shot_marker": ONE_SHOT_MARKER_LABEL,
        },
        "execution_controls": {
            "candidate_executed": False,
            "native_particle_frames_loaded": False,
            "canary_started": False,
            "tracer_started": False,
            "solver_started": False,
            "gpu_initialized": False,
            "worker_or_queue_started": False,
            "T2_started": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
        },
        "candidate_card_binding": {
            "path": CARD_REL.as_posix(),
            "bytes": len(card_bytes),
            "sha256": hashlib.sha256(card_bytes).hexdigest(),
        },
        "static_bindings": static_bindings,
    }


def validate_authorization(value: dict[str, Any]) -> None:
    contract = value.get("preflight_contract", {})
    controls = value.get("execution_controls", {})
    source = contract.get("source", {})
    card_binding = value.get("candidate_card_binding", {})
    exact_fields = {
        "schema", "status", "authority", "candidate_id", "attempt_id",
        "max_preflight_attempts", "same_scope_retry_allowed", "runtime_execution_authorized",
        "preflight_contract", "execution_controls", "candidate_card_binding", "static_bindings",
    }
    exact_contract_fields = {
        "source", "native_rows_inclusive", "seed_denominator", "q", "dp_m",
        "substeps_if_later_separately_authorized", "support_cap", "minimum_ram_bytes",
        "minimum_disk_bytes", "max_static_binding_bytes", "fresh_output_namespace",
        "one_shot_marker",
    }
    exact_source_fields = {"path", "bytes", "sha256", "frame_count", "particle_count"}
    exact_control_fields = {
        "candidate_executed", "native_particle_frames_loaded", "canary_started",
        "tracer_started", "solver_started", "gpu_initialized", "worker_or_queue_started",
        "T2_started", "registry_mutation", "ledger_mutation",
    }
    if (
        set(value) != exact_fields
        or set(contract) != exact_contract_fields
        or set(source) != exact_source_fields
        or set(controls) != exact_control_fields
        or set(card_binding) != {"path", "bytes", "sha256"}
    ):
        raise ValueError("authorization contains missing or unregistered fields")
    if not (
        value.get("schema") == AUTH_SCHEMA
        and value.get("status") == "authorized_one_cpu_native_canary_preflight_runtime_not_authorized"
        and value.get("authority") == "explicit user authorization: F4 supportcap one CPU/native canary preflight"
        and value.get("candidate_id") == CANDIDATE_ID
        and value.get("attempt_id") == ATTEMPT_ID
        and value.get("max_preflight_attempts") == 1
        and value.get("same_scope_retry_allowed") is False
        and value.get("runtime_execution_authorized") is False
        and contract.get("source") == SOURCE_IDENTITY
        and contract.get("native_rows_inclusive") == NATIVE_ROWS
        and contract.get("seed_denominator") == SEED_DENOMINATOR
        and contract.get("q") == Q
        and contract.get("dp_m") == DP_M
        and contract.get("substeps_if_later_separately_authorized") == SUBSTEPS
        and contract.get("support_cap") == SUPPORT_CAP
        and contract.get("minimum_ram_bytes") == MIN_RAM_BYTES
        and contract.get("minimum_disk_bytes") == MIN_DISK_BYTES
        and contract.get("max_static_binding_bytes") == MAX_STATIC_BYTES
        and contract.get("fresh_output_namespace") == OUTPUT_REL.as_posix()
        and contract.get("one_shot_marker") == ONE_SHOT_MARKER_LABEL
        and controls.get("candidate_executed") is False
        and controls.get("native_particle_frames_loaded") is False
        and controls.get("canary_started") is False
        and controls.get("tracer_started") is False
        and controls.get("solver_started") is False
        and controls.get("gpu_initialized") is False
        and controls.get("worker_or_queue_started") is False
        and controls.get("T2_started") is False
        and controls.get("registry_mutation") == 0
        and controls.get("ledger_mutation") == 0
    ):
        raise ValueError("authorization does not bind the exact preflight-only scope")


def validate_static_bindings(value: dict[str, Any]) -> None:
    validate_authorization(value)
    bindings = value.get("static_bindings", [])
    if not isinstance(bindings, list) or any(not isinstance(row, dict) for row in bindings):
        raise ValueError("preflight static bindings must be an array of objects")
    by_path = {row.get("path"): row for row in bindings}
    expected = {path.as_posix() for path in CANDIDATE_INPUTS.values()}
    expected.update({CARD_REL.as_posix(), SCRIPT_REL.as_posix(), TEST_REL.as_posix()})
    if len(by_path) != len(bindings) or set(by_path) != expected:
        raise ValueError("preflight static binding set differs from the candidate closure")
    payloads: dict[str, bytes] = {}
    for row in bindings:
        relative = Path(row["path"])
        if (
            set(row) != {"path", "bytes", "sha256"}
            or relative.is_absolute() or ".." in relative.parts
            or not isinstance(row.get("bytes"), int) or isinstance(row.get("bytes"), bool)
            or not 0 < row["bytes"] <= MAX_STATIC_BYTES
            or not isinstance(row.get("sha256"), str) or len(row["sha256"]) != 64
        ):
            raise ValueError(f"invalid static binding: {relative}")
        path = LAB / relative
        payload = _read_bounded(path)
        if len(payload) != row["bytes"] or hashlib.sha256(payload).hexdigest() != row["sha256"]:
            raise ValueError(f"static binding digest/size mismatch: {relative}")
        payloads[relative.as_posix()] = payload
    card_payload = payloads[CARD_REL.as_posix()]
    actual_card_binding = {
        "path": CARD_REL.as_posix(),
        "bytes": len(card_payload),
        "sha256": hashlib.sha256(card_payload).hexdigest(),
    }
    if actual_card_binding != value["candidate_card_binding"]:
        raise ValueError("authorization candidate-card digest mismatch")
    if actual_card_binding["sha256"] != FROZEN_CARD_SHA256:
        raise ValueError("candidate card differs from the reviewed, code-pinned card digest")
    card = _decode_frozen_candidate_card(card_payload)
    card_bindings = card.get("input_bindings")
    if not isinstance(card_bindings, dict) or set(card_bindings) != set(CANDIDATE_INPUTS):
        raise ValueError("bound candidate card has an incomplete input closure")
    for role, expected_path in CANDIDATE_INPUTS.items():
        row = card_bindings[role]
        if not isinstance(row, dict) or row != by_path.get(expected_path.as_posix()):
            raise ValueError(f"authorization differs from the pinned candidate-card binding: {role}")


def read_authorization() -> tuple[dict[str, Any], dict[str, Any]]:
    payload = _read_bounded(AUTH_PATH)
    value = json.loads(payload.decode("utf-8"))
    return value, {"path": AUTH_REL.as_posix(), "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def configure_cpu_environment() -> dict[str, Any]:
    global _ORIGINAL_ENVIRONMENT
    _ORIGINAL_ENVIRONMENT = {name: os.environ.get(name) for name in THREAD_ENV}
    _ORIGINAL_ENVIRONMENT["CUDA_VISIBLE_DEVICES"] = os.environ.get("CUDA_VISIBLE_DEVICES")
    for name in THREAD_ENV:
        os.environ[name] = "1"
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    return _ORIGINAL_ENVIRONMENT


def _available_ram_bytes() -> int:
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    raise RuntimeError("MemAvailable is missing from /proc/meminfo")


def _active_material_workers() -> list[int]:
    markers = (
        b"scripts/f3_native_volume_mls.py",
        b"scripts/f4_tallwall120_material.py",
        b"scripts/f4_supportcap_affine_query_bound_cpu_canary_execute_v1.py",
        b"scripts/f4_supportcap_affine_shepard_blend_cpu_canary_execute_v1.py",
    )
    pids = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            command = (entry / "cmdline").read_bytes().replace(b"\0", b" ")
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if any(marker in command for marker in markers):
            pids.append(int(entry.name))
    return sorted(pids)


def environment_preflight() -> dict[str, Any]:
    if any(os.environ.get(name) != "1" for name in THREAD_ENV) or os.environ.get("CUDA_VISIBLE_DEVICES", ""):
        raise RuntimeError("one CPU thread and hidden CUDA devices are required")
    import h5py
    import numpy as np
    import scipy

    cpu_count = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1)
    return {
        "created_at_utc": _stamp(),
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "h5py": h5py.__version__,
        "environment": {
            "thread_limits": {name: os.environ.get(name) for name in THREAD_ENV},
            "original": _ORIGINAL_ENVIRONMENT,
            "CUDA_VISIBLE_DEVICES": os.environ.get("CUDA_VISIBLE_DEVICES", ""),
        },
        "resources": {
            "process_visible_cpu_count": cpu_count,
            "load_average_1_5_15_min": list(os.getloadavg()),
            "available_ram_bytes": _available_ram_bytes(),
            "minimum_ram_bytes": MIN_RAM_BYTES,
            "filesystem_free_bytes": shutil.disk_usage(LAB).free,
            "minimum_filesystem_free_bytes": MIN_DISK_BYTES,
            "active_material_worker_pids": _active_material_workers(),
        },
        "controls": {
            "preflight_only": True,
            "candidate_executed": False,
            "native_particle_frames_loaded": False,
            "canary_started": False,
            "tracer_started": False,
            "solver_started": False,
            "gpu_initialized": False,
            "worker_or_queue_started": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
        },
    }


def resource_blockers(environment: dict[str, Any]) -> list[str]:
    resources = environment["resources"]
    blockers = []
    if resources["load_average_1_5_15_min"][0] > resources["process_visible_cpu_count"]:
        blockers.append("one-minute load exceeds process-visible CPU capacity")
    if resources["available_ram_bytes"] < MIN_RAM_BYTES:
        blockers.append("available RAM is below the 16 GiB floor")
    if resources["filesystem_free_bytes"] < MIN_DISK_BYTES:
        blockers.append("free filesystem space is below the 8 GiB floor")
    if resources["active_material_worker_pids"]:
        blockers.append("F3/F4 material worker is active")
    return blockers


def input_preflight() -> dict[str, Any]:
    if any(os.environ.get(name) != "1" for name in THREAD_ENV) or os.environ.get("CUDA_VISIBLE_DEVICES", ""):
        raise RuntimeError("CPU-only environment is required before source access")
    import h5py
    import numpy as np

    source = SOURCE_PATH
    descriptor = _open_absolute_regular(source)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size != SOURCE_IDENTITY["bytes"]:
            raise ValueError("source file type or size differs from the frozen identity")
        signature = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        digest = hashlib.sha256()
        stream.seek(0)
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
        after_hash = os.fstat(stream.fileno())
        if signature != (after_hash.st_dev, after_hash.st_ino, after_hash.st_size, after_hash.st_mtime_ns, after_hash.st_ctime_ns):
            raise ValueError("source changed during SHA-256 verification")
        if digest.hexdigest() != SOURCE_IDENTITY["sha256"]:
            raise ValueError("source SHA-256 differs from the frozen T1 input identity")
        stream.seek(0)
        with h5py.File(stream, "r") as handle:
            required = {"time", "position", "velocity", "valid", "particle_zone"}
            missing = sorted(required - set(handle))
            if missing:
                raise ValueError(f"source lacks required datasets: {missing}")
            frames = SOURCE_IDENTITY["frame_count"]
            particles = SOURCE_IDENTITY["particle_count"]
            shapes_ok = (
                handle["position"].shape == handle["velocity"].shape == (frames, particles, 3)
                and handle["valid"].shape == (frames, particles)
                and handle["particle_zone"].shape == (particles,)
                and handle["time"].shape == (frames,)
            )
            times = np.asarray(handle["time"][NATIVE_ROWS[0] : NATIVE_ROWS[1] + 1], dtype=np.float64)
            time_ok = times.shape == (42,) and np.isfinite(times).all() and np.all(np.diff(times) > 0)
            if not (shapes_ok and time_ok):
                raise ValueError("source dataset layout or native row-0-to-41 time axis is invalid")
        after_hdf5 = os.fstat(stream.fileno())
        if signature != (after_hdf5.st_dev, after_hdf5.st_ino, after_hdf5.st_size, after_hdf5.st_mtime_ns, after_hdf5.st_ctime_ns):
            raise ValueError("source changed during read-only HDF5 metadata validation")
    return {
        "source": {"path": str(source.relative_to(LAB)), **SOURCE_IDENTITY, "read_only": True},
        "source_hdf5_opened_after_hash_match": True,
        "datasets_and_shapes_validated": True,
        "native_window": {
            "first_row": NATIVE_ROWS[0],
            "last_row_inclusive": NATIVE_ROWS[1],
            "saved_rows": int(len(times)),
            "time_start_s": float(times[0]),
            "time_end_s": float(times[-1]),
            "times_strictly_increasing": True,
        },
        "native_particle_frames_loaded": False,
        "candidate_executed": False,
        "qualification_credit": 0,
    }


def _write_payload_at(directory_fd: int, name: str, value: dict[str, Any]) -> None:
    payload = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    descriptor = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        0o600,
        dir_fd=directory_fd,
    )
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.fsync(directory_fd)


def _write_once_at(directory_fd: int, name: str, value: dict[str, Any]) -> None:
    if name not in {LOCK_NAME, RECEIPT_NAME, ONE_SHOT_MARKER_NAME}:
        raise ValueError("preflight writer accepts only fixed marker/lock/receipt filenames")
    _write_payload_at(directory_fd, name, value)


def _write_once(path: Path, value: dict[str, Any]) -> None:
    path = Path(path)
    if path != AUTH_PATH:
        raise ValueError("static writer accepts only the fixed authorization path")
    directory_fd = _open_absolute_directory(path.parent, create=True)
    try:
        _write_payload_at(directory_fd, path.name, value)
    finally:
        os.close(directory_fd)


def _require_absent_at(directory_fd: int, name: str, message: str) -> None:
    try:
        os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise FileExistsError(message)


def run_preflight() -> dict[str, Any]:
    """Run only the fixed, hash-bound v5 preflight scope; no caller overrides."""
    authorization, authorization_binding = read_authorization()
    validate_static_bindings(authorization)
    state_fd = _open_private_state_directory()
    try:
        scope_fd = _open_absolute_directory(SCOPE_DIR)
    except Exception:
        os.close(state_fd)
        raise
    try:
        output_parent_fd = _open_absolute_directory(OUTPUT_NAMESPACE.parent)
    except Exception:
        os.close(scope_fd)
        os.close(state_fd)
        raise
    try:
        _require_path_matches_directory_fd(STATE_DIR, state_fd, "one-shot state")
        _require_path_matches_directory_fd(SCOPE_DIR, scope_fd, "one-shot scope")
        _require_path_matches_directory_fd(OUTPUT_NAMESPACE.parent, output_parent_fd, "output namespace parent")
        _require_absent_at(state_fd, ONE_SHOT_MARKER_NAME, "the one authorized F4 v5 preflight is already consumed")
        _require_absent_at(scope_fd, LOCK_NAME, "the one authorized F4 v5 preflight is already consumed")
        _require_absent_at(scope_fd, RECEIPT_NAME, "the one authorized F4 v5 preflight is already consumed")
        _require_absent_at(output_parent_fd, OUTPUT_NAMESPACE.name, "fresh v5 canary namespace must be absent")

        first_environment = environment_preflight()
        first_blockers = resource_blockers(first_environment)
        if first_blockers:
            return {
                "schema": SCHEMA,
                "status": "deferred_before_one_shot_consumed",
                "preflight_started": False,
                "authorization_consumed": False,
                "environment_preflight": first_environment,
                "resource_blockers": first_blockers,
                "retry_policy": {"preflight_attempts": 1, "same_scope_retry_allowed": False},
                "execution_controls": {"candidate_executed": False, "native_particle_frames_loaded": False, "canary_started": False, "tracer_started": False, "solver_started": False, "gpu_initialized": False, "worker_or_queue_started": False, "registry_mutation": 0, "ledger_mutation": 0},
            }

        started = {
            "schema": SCHEMA,
            "attempt_id": ATTEMPT_ID,
            "started_at_utc": _stamp(),
            "status": "preflight_started_runtime_not_authorized",
            "preflight_started": True,
            "authorization_consumed": True,
            "preflight_only": True,
            "runtime_execution_authorized": False,
            "same_scope_retry_allowed": False,
            "authorization_binding": authorization_binding,
            "one_shot_marker": ONE_SHOT_MARKER_LABEL,
        }
        _write_once_at(state_fd, ONE_SHOT_MARKER_NAME, started)
        _write_once_at(scope_fd, LOCK_NAME, started)

        environment = first_environment
        blockers: list[str] = []
        inputs: dict[str, Any] | None = None
        failure: str | None = None
        status = "preflight_failed_runtime_not_authorized"
        try:
            environment = environment_preflight()
            blockers = resource_blockers(environment)
            if blockers:
                status = "preflight_deferred_resource_gate_runtime_not_authorized"
            else:
                _require_path_matches_directory_fd(STATE_DIR, state_fd, "one-shot state")
                _require_path_matches_directory_fd(SCOPE_DIR, scope_fd, "one-shot scope")
                _require_path_matches_directory_fd(OUTPUT_NAMESPACE.parent, output_parent_fd, "output namespace parent")
                inputs = input_preflight()
                _require_path_matches_directory_fd(STATE_DIR, state_fd, "one-shot state")
                _require_path_matches_directory_fd(SCOPE_DIR, scope_fd, "one-shot scope")
                _require_path_matches_directory_fd(OUTPUT_NAMESPACE.parent, output_parent_fd, "output namespace parent")
                _require_absent_at(output_parent_fd, OUTPUT_NAMESPACE.name, "canary namespace appeared during preflight")
                status = "preflight_passed_runtime_not_authorized"
        except Exception as error:
            failure = f"{type(error).__name__}: {error}"
        receipt = {
            "schema": SCHEMA,
            "attempt_id": ATTEMPT_ID,
            "created_at_utc": _stamp(),
            "status": status,
            "preflight_started": True,
            "authorization_consumed": True,
            "candidate_id": CANDIDATE_ID,
            "authorization_binding": authorization_binding,
            "environment_preflight": environment,
            "resource_blockers": blockers,
            "input_preflight": inputs,
            "failure": failure,
            "execution_controls": {
                "preflight_only": True,
                "candidate_executed": False,
                "native_particle_frames_loaded": False,
                "canary_started": False,
                "tracer_started": False,
                "solver_started": False,
                "gpu_initialized": False,
                "worker_or_queue_started": False,
                "T2_started": False,
                "registry_mutation": 0,
                "ledger_mutation": 0,
                "qualification_credit": 0,
            },
            "retry_policy": {"preflight_attempts": 1, "same_scope_retry_allowed": False},
        }
        _write_once_at(scope_fd, RECEIPT_NAME, receipt)
        return receipt
    finally:
        os.close(output_parent_fd)
        os.close(scope_fd)
        os.close(state_fd)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("authorize", "run"))
    args = parser.parse_args()
    if args.command == "authorize":
        _write_once(AUTH_PATH, build_authorization())
        print(json.dumps({"status": "one_shot_preflight_authorization_frozen", "path": AUTH_REL.as_posix()}, sort_keys=True))
        return 0
    configure_cpu_environment()
    result = run_preflight()
    print(json.dumps({"status": result["status"], "preflight_started": result.get("preflight_started", result.get("status") != "deferred_before_one_shot_consumed"), "authorization_consumed": result.get("authorization_consumed", True), "resource_blockers": result.get("resource_blockers", [])}, sort_keys=True))
    return 2 if result["status"] != "preflight_passed_runtime_not_authorized" else 0


if __name__ == "__main__":
    raise SystemExit(main())
