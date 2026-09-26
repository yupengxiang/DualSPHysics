from __future__ import annotations

import hashlib
import json
from pathlib import Path

import h5py
import numpy as np
import pytest

from scripts.f4_supportcap_local_affine_reconstruction_preflight_v1 import (
    AUTHORIZATION,
    CANDIDATE_ID,
    MIN_DISK_BYTES,
    MIN_RAM_BYTES,
    RECEIPT_SCHEMA,
    REQUIRED_STATIC_BINDINGS,
    SOURCE_BYTES,
    SOURCE_FRAMES,
    SOURCE_PARTICLES,
    SOURCE_SHA256,
    THREAD_ENV,
    input_preflight,
    read_authorization,
    resource_blockers,
    run_preflight,
    validate_static_bindings,
)


def _small_h5(path: Path) -> tuple[int, str]:
    times = np.array([0.0, 0.1, 0.2], dtype=np.float64)
    position = np.zeros((3, 4, 3), dtype=np.float64)
    velocity = np.ones((3, 4, 3), dtype=np.float64)
    with h5py.File(path, "w") as handle:
        handle["time"] = times
        handle["position"] = position
        handle["velocity"] = velocity
        handle["valid"] = np.ones((3, 4), dtype=bool)
        handle["particle_zone"] = np.full(4, 3, dtype=np.int8)
    return path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest()


def _small_auth(path: Path, size: int, digest: str) -> dict:
    return {
        "preflight_contract": {
            "native_rows_inclusive": [0, 2],
            "source": {
                "path": "small.h5",
                "bytes": size,
                "sha256": digest,
                "frame_count": 3,
                "particle_count": 4,
            }
        }
    }


def test_live_authorization_and_all_static_bindings_are_hash_closed() -> None:
    authorization, binding = read_authorization()
    validate_static_bindings(authorization)
    assert binding["path"].endswith("cpu-native-preflight-v1/authorization.json")
    paths = {entry["path"] for entry in authorization["static_bindings"]}
    assert REQUIRED_STATIC_BINDINGS <= paths
    assert authorization["authorization"]["candidate_id"] == CANDIDATE_ID
    assert authorization["authorization"]["runtime_execution_authorized"] is False
    assert authorization["preflight_contract"]["source"]["bytes"] == SOURCE_BYTES
    assert authorization["preflight_contract"]["source"]["sha256"] == SOURCE_SHA256
    assert authorization["preflight_contract"]["source"]["frame_count"] == SOURCE_FRAMES
    assert authorization["preflight_contract"]["source"]["particle_count"] == SOURCE_PARTICLES


def test_resource_gate_blocks_before_any_source_probe(tmp_path: Path) -> None:
    authorization, binding = read_authorization()
    scope = tmp_path / "scope"
    scope.mkdir()
    canary_namespace = tmp_path / "future-canary"
    environment = {
        "resources": {
            "load_average_1_5_15_min": [999.0, 1.0, 1.0],
            "available_cpu_count": 8,
            "available_ram_bytes": MIN_RAM_BYTES,
            "filesystem_free_bytes": MIN_DISK_BYTES,
            "active_material_worker_pids": [],
        }
    }
    result = run_preflight(
        authorization,
        scope_dir=scope,
        canary_namespace=canary_namespace,
        authorization_binding=binding,
        resource_probe=lambda: environment,
        source_probe=lambda _auth: pytest.fail("source preflight must short-circuit on resource hold"),
    )
    assert result["schema"] == RECEIPT_SCHEMA
    assert result["status"] == "preflight_deferred_resource_gate_runtime_not_authorized"
    assert result["input_preflight"] is None
    assert result["execution_controls"]["canary_started"] is False
    assert result["execution_controls"]["tracer_started"] is False
    assert result["execution_controls"]["solver_started"] is False
    assert result["execution_controls"]["gpu_initialized"] is False
    assert result["execution_controls"]["worker_or_queue_started"] is False
    assert (scope / "one-shot-lock.json").is_file()
    assert (scope / "preflight-receipt.json").is_file()
    assert not canary_namespace.exists()


def test_preflight_lock_prevents_same_scope_retry(tmp_path: Path) -> None:
    authorization, binding = read_authorization()
    scope = tmp_path / "scope"
    scope.mkdir()
    canary_namespace = tmp_path / "future-canary"
    environment = {
        "resources": {
            "load_average_1_5_15_min": [0.0, 0.0, 0.0],
            "available_cpu_count": 8,
            "available_ram_bytes": MIN_RAM_BYTES,
            "filesystem_free_bytes": MIN_DISK_BYTES,
            "active_material_worker_pids": [],
        }
    }
    source_probe = lambda _auth: {"probe": "test-only"}
    run_preflight(
        authorization,
        scope_dir=scope,
        canary_namespace=canary_namespace,
        authorization_binding=binding,
        resource_probe=lambda: environment,
        source_probe=source_probe,
    )
    with pytest.raises(FileExistsError, match="already consumed"):
        run_preflight(
            authorization,
            scope_dir=scope,
            canary_namespace=canary_namespace,
            authorization_binding=binding,
            resource_probe=lambda: environment,
            source_probe=source_probe,
        )


def test_input_preflight_hashes_then_opens_same_small_readonly_fd(tmp_path: Path, monkeypatch) -> None:
    for name in THREAD_ENV:
        monkeypatch.setenv(name, "1")
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")
    source = tmp_path / "small.h5"
    size, digest = _small_h5(source)
    result = input_preflight(_small_auth(source, size, digest), source=source, lab=tmp_path)
    assert result["source"]["bytes"] == size
    assert result["source"]["sha256"] == digest
    assert result["source_hdf5_opened_after_hash_match"] is True
    assert result["datasets_and_shapes_validated"] is True
    assert result["native_window"]["saved_rows"] == 3
    assert result["native_particle_frames_loaded"] is False
    assert result["qualification_credit"] == 0


def test_wrong_source_hash_fails_before_hdf5_open(tmp_path: Path, monkeypatch) -> None:
    for name in THREAD_ENV:
        monkeypatch.setenv(name, "1")
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")
    source = tmp_path / "small.h5"
    size, _ = _small_h5(source)
    with pytest.raises(ValueError, match="SHA-256"):
        input_preflight(_small_auth(source, size, "0" * 64), source=source, lab=tmp_path)


def test_environment_blockers_preserve_fixed_resource_floors() -> None:
    blockers = resource_blockers(
        {
            "resources": {
                "load_average_1_5_15_min": [1.0, 1.0, 1.0],
                "available_cpu_count": 8,
                "available_ram_bytes": MIN_RAM_BYTES - 1,
                "filesystem_free_bytes": MIN_DISK_BYTES - 1,
                "active_material_worker_pids": [1234],
            }
        }
    )
    assert len(blockers) == 3
