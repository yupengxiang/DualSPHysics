#!/usr/bin/env python3
"""Execute the one explicitly authorized F4 supportcap CPU canary exactly once.

The runner is intentionally narrower than a material job: it verifies the
hash-bound authorization before it opens the source, reads only native frames
40 and 41 through a read-only two-frame provider, and writes one fresh,
immutable output namespace.  It has no solver, GPU, queue, scheduler,
registry, ledger, or matrix-writer entry point.  Its short result remains
right-censored and has zero qualification credit regardless of outcome.
"""
from __future__ import annotations

import argparse
from collections import OrderedDict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import threading
from typing import Any

import h5py
import numpy as np
import scipy


LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts import core_material as cm
from scripts import f4_supportcap_affine_query_bound_candidate_v3 as candidate
from scripts import f4_tallwall120_material as tracer


AUTHORIZATION = LAB / (
    "campaigns/core-v1/material/candidates/f4-supportcap-affine-query-bound-v3/"
    "cpu-native-canary-preflight-authorization-v1/authorization.json"
)
ATTEMPT_ID = "f4-supportcap-affine-query-bound-v3-cpu-native-canary-r001"
OUTPUT = LAB / "campaigns/core-v1/material/evidence" / ATTEMPT_ID
SCHEMA = "core.material.f4.supportcap_affine_query_bound.cpu_canary_execution.v1"
EXECUTION_AUTHORITY = "explicit user authorization: F4 supportcap CPU canary execution"
MIN_RAM_BYTES = 16 * 1024**3
MIN_FREE_BYTES = 8 * 1024**3
REQUIRED_ENVIRONMENT = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
}


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def file_ref(path: Path, role: str, *, known_sha256: str | None = None) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"missing {role}: {path}")
    return {
        "path": str(path.relative_to(LAB)),
        "role": role,
        "bytes": path.stat().st_size,
        "sha256": known_sha256 or sha256(path),
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"immutable canary artifact already exists: {path}")
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _mem_available_bytes() -> int:
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    raise RuntimeError("/proc/meminfo has no MemAvailable")


def _relative(path: Path) -> str:
    return str(Path(path).resolve().relative_to(LAB))


def _hash_bound(path: Path, binding: dict[str, Any], label: str) -> None:
    if _relative(path) != binding["path"] or sha256(path) != binding["sha256"]:
        raise ValueError(f"{label} hash binding does not match authorization")


def load_and_validate_authorization() -> dict[str, Any]:
    authorization = load_json(AUTHORIZATION)
    if authorization.get("schema") != "core.material.f4.supportcap_affine_query_bound.cpu_canary_authorization.v1":
        raise ValueError("unexpected CPU canary authorization schema")
    scope = authorization.get("authorization", {})
    one_attempt = authorization.get("one_attempt_contract", {})
    if not (
        scope.get("attempt_id") == ATTEMPT_ID
        and scope.get("candidate_id") == candidate.CANDIDATE_ID
        and scope.get("authorization_grants_runtime_execution") is False
        and one_attempt.get("max_attempts") == 1
        and one_attempt.get("retry") is False
        and one_attempt.get("new_output_namespace") == _relative(OUTPUT)
        and one_attempt.get("output_namespace_must_be_absent_before_start") is True
    ):
        raise ValueError("authorization does not bind this one-attempt executor")
    if OUTPUT.exists():
        raise FileExistsError("one-shot output namespace already exists; retry is forbidden")
    bindings = authorization["hash_bindings"]
    _hash_bound(
        LAB / bindings["candidate_card_v3"]["path"], bindings["candidate_card_v3"], "candidate card"
    )
    _hash_bound(
        LAB / bindings["terra_high_root_review_v4"]["path"],
        bindings["terra_high_root_review_v4"],
        "Terra High review",
    )
    _hash_bound(
        LAB / bindings["static_candidate_implementation"]["path"],
        bindings["static_candidate_implementation"],
        "candidate implementation",
    )
    bounded = authorization["input_contract"]["bounded_canary"]
    spec = candidate.candidate_spec()
    if not (
        bounded == {
            "frame_start": 40,
            "frame_stop_inclusive": 41,
            "seed_denominator": 512,
            "q": 0.5,
            "dp_m": 0.0075,
            "substeps": 2,
            "purpose": "one-transition CPU integration and fixed-gate preflight only",
        }
        and spec["backend"] == cm.F4_V3_BACKEND
        and spec["mechanisms"][0]["neighbours"] == cm.F4_V3_NEIGHBOURS
        and spec["mechanisms"][1]["error_estimator"] == cm.F4_V3_ERROR_ESTIMATOR
        and spec["fixed_gate"] == cm.GATE
    ):
        raise ValueError("registered supportcap/affine candidate contract changed")
    return authorization


def environment_preflight() -> dict[str, Any]:
    cuda_visible = os.environ.get("CUDA_VISIBLE_DEVICES", "")
    if cuda_visible.strip():
        raise ValueError("CUDA_VISIBLE_DEVICES must be empty for the CPU-only canary")
    for name, expected in REQUIRED_ENVIRONMENT.items():
        if os.environ.get(name) != expected:
            raise ValueError(f"{name} must be exactly {expected!r}")
    if sys.version_info < (3, 10):
        raise ValueError("Python >= 3.10 is required")
    ram = _mem_available_bytes()
    free = shutil.disk_usage(OUTPUT.parent).free
    if ram < MIN_RAM_BYTES:
        raise ValueError(f"available RAM {ram} is below required {MIN_RAM_BYTES}")
    if free < MIN_FREE_BYTES:
        raise ValueError(f"free filesystem capacity {free} is below required {MIN_FREE_BYTES}")
    return {
        "schema": "core.material.f4.supportcap_affine_query_bound.cpu_canary_environment_preflight.v1",
        "created_at_utc": stamp(),
        "python_version": sys.version.split()[0],
        "numpy_version": np.__version__,
        "scipy_version": scipy.__version__,
        "h5py_version": h5py.__version__,
        "environment": {
            "CUDA_VISIBLE_DEVICES": cuda_visible,
            "NVIDIA_VISIBLE_DEVICES": os.environ.get("NVIDIA_VISIBLE_DEVICES"),
            **{name: os.environ[name] for name in REQUIRED_ENVIRONMENT},
        },
        "resources": {
            "available_ram_bytes": ram,
            "minimum_ram_bytes": MIN_RAM_BYTES,
            "filesystem_free_bytes": free,
            "minimum_filesystem_free_bytes": MIN_FREE_BYTES,
            "cpu_workers": 1,
            "max_concurrent_processes": 1,
            "python_thread_count": threading.active_count(),
        },
        "controls": {
            "gpu_api_initialized": False,
            "solver_started": False,
            "queue_mutation": 0,
            "worker_scheduler_started": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "matrix_writer_started": False,
        },
    }


class TwoFrameNativeProvider:
    """Read exactly a registered adjacent native-frame pair, read-only."""

    provider_role = "reference"
    temporal_interpolation = "linear x/v only within native source frames 40 and 41"
    scope_id = tracer.SCOPE_ID
    revision_id = tracer.REVISION_ID
    material_recipe_id = tracer.MATERIAL_RECIPE_ID
    candidate_id = candidate.CANDIDATE_ID
    implementation_path = Path(candidate.__file__).resolve()

    def __init__(self, source: Path, source_sha256: str, *, start: int, stop: int) -> None:
        if stop != start + 1:
            raise ValueError("two-frame provider requires exactly one adjacent transition")
        self.source = Path(source).resolve()
        self.source_sha256 = source_sha256
        self.start = int(start)
        self.stop = int(stop)
        self.h5 = h5py.File(self.source, "r")
        self.cache: OrderedDict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = OrderedDict()
        self.loaded_native_indices: list[int] = []
        self.read_count = 0
        self.times = np.asarray(self.h5["time"][self.start : self.stop + 1], dtype=np.float64)
        if self.times.shape != (2,) or not np.isfinite(self.times).all() or self.times[1] <= self.times[0]:
            self.close()
            raise ValueError("native frame 40->41 time interval is invalid")
        self.particle_zone = np.asarray(self.h5["particle_zone"][:])
        self.particle_count = int(self.h5["position"].shape[1])

    def _check_index(self, index: int) -> int:
        if isinstance(index, bool) or not isinstance(index, (int, np.integer)) or int(index) not in (0, 1):
            raise IndexError("two-frame provider index is outside local frames 40..41")
        return int(index)

    def frame(self, index: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        index = self._check_index(index)
        if index in self.cache:
            self.cache.move_to_end(index)
            return self.cache[index]
        native_index = self.start + index
        position = np.asarray(self.h5["position"][native_index], dtype=np.float64)
        velocity = np.asarray(self.h5["velocity"][native_index], dtype=np.float64)
        valid = np.asarray(self.h5["valid"][native_index], dtype=bool)
        valid &= self.particle_zone == 0
        valid &= np.isfinite(position).all(axis=1) & np.isfinite(velocity).all(axis=1)
        for array in (position, velocity, valid):
            array.setflags(write=False)
        result = (position, velocity, valid)
        self.cache[index] = result
        self.loaded_native_indices.append(native_index)
        self.read_count += 1
        return result

    def field(self, index: int, alpha: float = 0.0) -> cm.CurrentField:
        index = self._check_index(index)
        if not np.isfinite(alpha) or not 0.0 <= alpha <= 1.0:
            raise ValueError("interpolation alpha must be in [0,1]")
        first = self.frame(index)
        if alpha == 0.0:
            return cm.CurrentField(*first)
        if index != 0:
            raise IndexError("frame 41 has no future native bracket")
        second = self.frame(1)
        common = first[2] & second[2]
        return cm.CurrentField(
            (1.0 - alpha) * first[0] + alpha * second[0],
            (1.0 - alpha) * first[1] + alpha * second[1],
            common,
        )

    def close(self) -> None:
        if getattr(self, "h5", None) is not None:
            self.h5.close()
            self.h5 = None


def input_preflight(authorization: dict[str, Any]) -> dict[str, Any]:
    source_contract = authorization["input_contract"]["source"]
    source = (LAB / source_contract["path"]).resolve()
    observed_sha = sha256(source)
    if observed_sha != source_contract["sha256"]:
        raise ValueError("source SHA256 does not match authorization before HDF5 open")
    required = {"time", "position", "velocity", "valid", "particle_zone"}
    with h5py.File(source, "r") as handle:
        missing = sorted(required - set(handle))
        if missing:
            raise ValueError(f"source misses required datasets: {missing}")
        time = np.asarray(handle["time"][40:42], dtype=np.float64)
        position = handle["position"]
        velocity = handle["velocity"]
        valid = handle["valid"]
        zone = handle["particle_zone"]
        if not (
            time.shape == (2,)
            and np.isfinite(time).all()
            and time[1] > time[0]
            and position.shape == velocity.shape == (source_contract["frame_count"], source_contract["particle_count"], 3)
            and valid.shape == (source_contract["frame_count"], source_contract["particle_count"])
            and zone.shape == (source_contract["particle_count"],)
        ):
            raise ValueError("native two-frame source layout is not authorization-compatible")
    return {
        "schema": "core.material.f4.supportcap_affine_query_bound.cpu_canary_input_preflight.v1",
        "created_at_utc": stamp(),
        "source": file_ref(source, "hash-matched read-only native trajectory", known_sha256=observed_sha),
        "read_only": True,
        "source_hdf5_opened_after_hash_match": True,
        "native_frame_window": {
            "start": 40,
            "stop_inclusive": 41,
            "time_start_s": float(time[0]),
            "time_stop_s": float(time[1]),
            "strictly_increasing": True,
            "native_rows_read_by_runner": [40, 41],
        },
        "fixed_contract": {
            "seed_denominator": 512,
            "q": 0.5,
            "dp_m": 0.0075,
            "substeps": 2,
            "neighbour_variant": candidate.CANDIDATE_ID,
            "backend": cm.F4_V3_BACKEND,
            "neighbours": cm.F4_V3_NEIGHBOURS,
            "error_estimator": cm.F4_V3_ERROR_ESTIMATOR,
            "gate": candidate.FIXED_GATE,
            "event_semantics": "registered F4 tallwall120 continuous event observer; short window remains right-censored",
        },
    }


def _attempt_manifest(authorization: dict[str, Any], environment: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "core.material.f4.supportcap_affine_query_bound.cpu_canary_attempt_manifest.v1",
        "attempt_id": ATTEMPT_ID,
        "created_at_utc": stamp(),
        "execution_authority": EXECUTION_AUTHORITY,
        "authorization": file_ref(AUTHORIZATION, "preflight authorization"),
        "executor": file_ref(Path(__file__), "hash-bound one-shot CPU executor"),
        "authorization_sha256_bound_by_executor": sha256(AUTHORIZATION),
        "output_namespace": _relative(OUTPUT),
        "max_attempts": 1,
        "retry": False,
        "resumption": "only within this same attempt; no retry after terminal receipt",
        "environment_preflight_sha256": hashlib.sha256(
            json.dumps(environment, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "input_preflight_sha256": hashlib.sha256(
            json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "execution_controls": {
            "solver_started": False,
            "gpu_started": False,
            "queue_mutation": 0,
            "worker_scheduler_started": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "matrix_writer_started": False,
            "historical_receipts_modified": False,
        },
        "qualification": {"claim": "none", "credit": 0, "T1_numerical": False, "T2_macro": False, "T2_path": False},
    }


def _gate_evaluation(result: dict[str, Any]) -> dict[str, Any]:
    rows = result.get("by_source", [])
    if len(rows) != 1:
        raise ValueError("one-source fixed denominator result is required")
    row = rows[0]
    denominator = 512
    unknown = float(row.get("unknown_fraction_max", 1.0))
    unknown_count = int(round(unknown * denominator))
    if not 0 <= unknown_count <= denominator or abs(unknown_count / denominator - unknown) > 1e-12:
        raise ValueError("unknown result no longer maps to the fixed 512-seed denominator")
    checks = {
        "source_mass_closed": bool(result.get("mass_closed")),
        "unknown_fraction_within_registered_limit": bool(unknown <= 0.01),
        "right_censored_as_required_for_one_transition": result.get("event_window_status") == "right_censored_or_unresolved",
        "candidate_backend_bound": result["binding"].get("backend") == cm.F4_V3_BACKEND,
        "candidate_support_cap_bound": result["binding"].get("neighbours") == 32,
        "candidate_affine_estimator_bound": result["binding"].get("error_estimator") == cm.F4_V3_ERROR_ESTIMATOR,
        "full_seed_denominator_bound": int(row.get("seed_count", 0)) == denominator,
    }
    return {
        "seed_denominator": denominator,
        "unknown_count": unknown_count,
        "unknown_fraction": unknown,
        "unknown_limit": 0.01,
        "checks": checks,
        "pass": bool(all(checks.values())),
        "right_censored": True,
    }


def _acceptance_receipt(
    *, authorization: dict[str, Any], result: dict[str, Any] | None, gate: dict[str, Any] | None,
    status: str, failure: str | None, provider: TwoFrameNativeProvider | None,
) -> dict[str, Any]:
    controls = {
        "canary_started": result is not None,
        "source_hdf5_opened": True,
        "source_hdf5_read_only": True,
        "solver_started": False,
        "gpu_started": False,
        "queue_mutation": 0,
        "worker_started": False,
        "registry_mutation": 0,
        "ledger_mutation": 0,
        "matrix_writer_started": False,
        "historical_receipts_modified": False,
    }
    return {
        "schema": SCHEMA,
        "record_id": ATTEMPT_ID + "-acceptance-receipt-v1",
        "created_at_utc": stamp(),
        "status": status,
        "execution_authority": EXECUTION_AUTHORITY,
        "authorization": file_ref(AUTHORIZATION, "preflight authorization"),
        "executor": file_ref(Path(__file__), "one-shot CPU executor"),
        "result": file_ref(OUTPUT / "result.json", "canary result") if (OUTPUT / "result.json").is_file() else None,
        "gate_evaluation": gate,
        "failure": failure,
        "native_read_provenance": {
            "authorized_native_frames": [40, 41],
            "loaded_native_indices": [] if provider is None else provider.loaded_native_indices,
            "only_authorized_native_rows_loaded": bool(
                provider is not None and set(provider.loaded_native_indices) <= {40, 41}
            ),
        },
        "execution_controls": controls,
        "qualification": {
            "qualification_claim": "none",
            "credit": 0,
            "T1_numerical": False,
            "T2_macro": False,
            "T2_path": False,
            "material_qualification": False,
            "reason": "one-transition CPU-only canary is right-censored and cannot supply material qualification",
        },
        "authorization_contract": {
            "success_status": authorization["acceptance_and_failure_semantics"]["success_status"],
            "failure_status": authorization["acceptance_and_failure_semantics"]["failure_status"],
            "same_input_retry": False,
        },
    }


def run_once(output: Path = OUTPUT) -> dict[str, Any]:
    if Path(output).resolve() != OUTPUT.resolve():
        raise ValueError("only the registered F4 one-shot output namespace is permitted")
    authorization = load_and_validate_authorization()
    environment = environment_preflight()
    inputs = input_preflight(authorization)
    # Namespace creation happens only after every mutable preflight passes.
    OUTPUT.mkdir(parents=True, exist_ok=False)
    write_json(OUTPUT / "attempt-manifest.json", _attempt_manifest(authorization, environment, inputs))
    write_json(OUTPUT / "environment-preflight.json", environment)
    write_json(OUTPUT / "input-preflight.json", inputs)
    source = LAB / authorization["input_contract"]["source"]["path"]
    provider: TwoFrameNativeProvider | None = None
    result: dict[str, Any] | None = None
    gate: dict[str, Any] | None = None
    status = authorization["acceptance_and_failure_semantics"]["failure_status"]
    failure: str | None = None
    try:
        provider = TwoFrameNativeProvider(
            source, inputs["source"]["sha256"], start=40, stop=41
        )
        result = tracer.trace_tallwall120(
            source,
            OUTPUT / "trace.h5",
            q=0.5,
            dp_m=0.0075,
            seeds=512,
            substeps=2,
            stop_after=1,
            provider=provider,
            neighbour_variant=candidate.CANDIDATE_ID,
        )
        if result is None:
            raise RuntimeError("tracer did not produce a terminal bounded result")
        write_json(OUTPUT / "result.json", result)
        gate = _gate_evaluation(result)
        if gate["pass"]:
            status = authorization["acceptance_and_failure_semantics"]["success_status"]
        else:
            failure = "one or more unchanged fixed canary gates failed"
    except Exception as error:  # retain a terminal negative receipt; never retry.
        failure = f"executor exception: {error!r}"
    finally:
        if provider is not None:
            provider.close()
    receipt = _acceptance_receipt(
        authorization=authorization, result=result, gate=gate, status=status,
        failure=failure, provider=provider,
    )
    write_json(OUTPUT / "acceptance-receipt.json", receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    receipt = run_once()
    print(json.dumps({"status": receipt["status"], "credit": 0}, sort_keys=True), flush=True)
    return 0 if receipt["status"] == "completed_cpu_canary_preflight_zero_credit" else 1


if __name__ == "__main__":
    raise SystemExit(main())
