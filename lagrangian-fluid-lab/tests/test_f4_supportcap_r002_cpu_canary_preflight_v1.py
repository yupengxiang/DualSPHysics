from __future__ import annotations

import ast
import hashlib
import importlib
import json
import os
from pathlib import Path

import numpy as np
import pytest

from scripts import f4_supportcap_r002_cpu_canary_preflight_v1 as preflight


def _design_recipe():
    return {
        "schema": "core.material.f4.supportcap_r002_static_temporal_alignment_design.v3",
        "record_id": "f4-supportcap-affine-query-bound-v3-r002-static-design-v3",
        "prospective_attempt": {
            "attempt_id": preflight.ATTEMPT_ID,
            "candidate_id": "f4_supportcap_affine_query_bound_v3",
            "q": 0.5,
            "dp_m": 0.0075,
            "denominator": 512,
            "substeps": 2,
            "support_cap": 32,
            "fresh_output_namespace": str(preflight.ATTEMPT_REL / "trace.h5"),
            "alignment": {
                "initial_native_frame": 0,
                "last_native_frame_inclusive": 41,
                "target_transition": [40, 41],
                "advect_initial_seeds_before_target_transition": True,
                "query_original_t0_seed_positions_at_row40": False,
            },
            "all_gates_and_event_censoring_unchanged": True,
        },
        "source_identity": {
            "path": str(preflight.SOURCE_REL),
            "sha256": preflight.SOURCE_SHA256,
        },
        "execution_authority": {
            "cpu_canary_authorized": False,
            "native_preflight_authorized": False,
            "solver_authorized": False,
            "gpu_authorized": False,
            "worker_or_queue_authorized": False,
            "qualification_credit": 0,
        },
        "historical_attempt": {
            "attempt_id": preflight.ATTEMPT_ID.replace("r002", "r001"),
            "modified": False,
            "retried": False,
        },
    }


def _authorization(tmp_path):
    lab = tmp_path / "lab"
    bindings = []
    for relative in sorted(preflight.REQUIRED_STATIC_BINDINGS):
        path = lab / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if relative == str(preflight.RECIPE_REL):
            payload = (json.dumps(_design_recipe(), sort_keys=True) + "\n").encode()
        else:
            payload = ("static fixture for " + relative + "\n").encode()
        path.write_bytes(payload)
        bindings.append({
            "path": relative,
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        })
    return {
        "schema": preflight.AUTH_SCHEMA,
        "status": "authorized_one_cpu_native_canary_preflight_runtime_not_authorized",
        "authorization": {
            "attempt_id": preflight.ATTEMPT_ID,
            "candidate_id": "f4_supportcap_affine_query_bound_v3",
            "grants_one_cpu_native_canary_preflight": True,
            "grants_runtime_execution": False,
        },
        "preflight_contract": {
            "max_preflight_attempts": 1,
            "same_input_retry_allowed": False,
            "native_rows_inclusive": [0, 41],
            "source_sha256": preflight.SOURCE_SHA256,
            "seed_denominator": 512,
            "q": 0.5,
            "dp_m": 0.0075,
            "substeps": 2,
            "output_namespace": str(preflight.ATTEMPT_REL / "trace.h5"),
            "source": {
                "path": str(preflight.SOURCE_REL),
                "bytes": preflight.SOURCE_BYTES,
                "sha256": preflight.SOURCE_SHA256,
                "frame_count": preflight.SOURCE_FRAMES,
                "particle_count": preflight.SOURCE_PARTICLES,
            },
        },
        "execution_controls": {
            "tracer_started": False,
            "solver_started": False,
            "gpu_started": False,
            "queue_or_scheduler_started": False,
            "t2_started": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
        },
        "static_bindings": bindings,
    }, lab


def _environment(*, load=0.1, active_workers=None):
    return {
        "resources": {
            "available_cpu_count": 8,
            "load_average_1_5_15_min": [load, load, load],
            "available_ram_bytes": preflight.MIN_RAM_BYTES,
            "filesystem_free_bytes": preflight.MIN_DISK_BYTES,
            "active_f3_material_worker_pids": active_workers or [],
        }
    }


def test_authorization_is_exactly_one_preflight_and_never_runtime(tmp_path):
    authorization, _lab = _authorization(tmp_path)
    preflight.validate_authorization(authorization)

    authorization["authorization"]["grants_runtime_execution"] = True
    with pytest.raises(ValueError, match="one-shot preflight-only"):
        preflight.validate_authorization(authorization)


def test_authorization_reader_returns_exact_file_hash(tmp_path):
    authorization, lab = _authorization(tmp_path)
    path = lab / "authorization.json"
    payload = (json.dumps(authorization, sort_keys=True) + "\n").encode()
    path.write_bytes(payload)
    parsed, binding = preflight.read_authorization(path, lab=lab)
    assert parsed == authorization
    assert binding == {
        "path": "authorization.json",
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def test_recipe_and_static_bindings_are_mandatory_and_exact(tmp_path):
    authorization, lab = _authorization(tmp_path)
    preflight.validate_static_bindings(authorization, lab=lab)

    recipe_path = lab / preflight.RECIPE_REL
    changed = _design_recipe()
    changed["prospective_attempt"]["q"] = 0.75
    payload = (json.dumps(changed, sort_keys=True) + "\n").encode()
    recipe_path.write_bytes(payload)
    recipe_binding = next(
        item for item in authorization["static_bindings"]
        if item["path"] == str(preflight.RECIPE_REL)
    )
    recipe_binding.update(bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
    with pytest.raises(ValueError, match="static recipe no longer matches"):
        preflight.validate_static_bindings(authorization, lab=lab)

    authorization["static_bindings"] = []
    with pytest.raises(ValueError, match="lacks required static bindings"):
        preflight.validate_static_bindings(authorization, lab=lab)


def test_recipe_is_parsed_from_verified_binding_bytes_not_reopened_path(tmp_path, monkeypatch):
    authorization, lab = _authorization(tmp_path)
    recipe_path = lab / preflight.RECIPE_REL
    original_read_text = Path.read_text

    def guarded_read_text(path, *args, **kwargs):
        if Path(path) == recipe_path:
            pytest.fail("recipe path was reopened after its binding was verified")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read_text)
    preflight.validate_static_bindings(authorization, lab=lab)


def test_static_bindings_reject_symlinks_and_oversized_artifacts(tmp_path):
    authorization, lab = _authorization(tmp_path)
    binding = next(
        item for item in authorization["static_bindings"]
        if item["path"].endswith("candidate-card-v3.json")
    )
    path = lab / binding["path"]
    path.unlink()
    path.symlink_to(lab / "scripts/core_material.py")
    with pytest.raises(ValueError, match="symlink is forbidden"):
        preflight.validate_static_bindings(authorization, lab=lab)

    path.unlink()
    path.write_text("restored fixture\n")
    binding["bytes"] = preflight.MAX_STATIC_BINDING_BYTES + 1
    with pytest.raises(ValueError, match="exceeds the text-artifact size limit"):
        preflight.validate_static_bindings(authorization, lab=lab)


def test_resource_gate_failure_is_terminal_and_skips_source_access(tmp_path, monkeypatch):
    authorization, lab = _authorization(tmp_path)
    scope = tmp_path / "scope"
    scope.mkdir()
    output = tmp_path / "new-output"
    source_calls = []
    directory_syncs = []
    monkeypatch.setattr(preflight, "_fsync_directory", lambda path: directory_syncs.append(Path(path)))

    def resource_probe():
        assert directory_syncs == [scope]
        return _environment(load=9.0, active_workers=[123])

    receipt = preflight.run_preflight(
        authorization,
        scope_dir=scope,
        output_dir=output,
        lab=lab,
        resource_probe=resource_probe,
        source_probe=lambda _auth: source_calls.append(True),
    )

    assert receipt["status"] == "preflight_deferred_resource_gate_no_runtime_authorization"
    assert len(receipt["resource_blockers"]) == 2
    assert not source_calls
    assert not output.exists()
    stored = json.loads((scope / "preflight-receipt.json").read_text())
    assert stored["status"] == receipt["status"]
    assert not (scope / "preflight-attempt.json").exists()
    assert receipt["execution_controls"]["canary_started"] is False
    assert receipt["scope"]["runtime_execution_authorized"] is False
    with pytest.raises(FileExistsError, match="already consumed"):
        preflight.run_preflight(
            authorization, scope_dir=scope, output_dir=output, lab=lab,
            resource_probe=lambda: _environment(),
        )


def test_passed_preflight_still_does_not_start_tracer_or_grant_runtime(tmp_path):
    authorization, lab = _authorization(tmp_path)
    scope = tmp_path / "scope"
    scope.mkdir()
    receipt = preflight.run_preflight(
        authorization,
        scope_dir=scope,
        output_dir=tmp_path / "new-output",
        lab=lab,
        resource_probe=lambda: _environment(),
        source_probe=lambda _auth: {"source_hdf5_opened_after_hash_match": True},
    )

    assert receipt["status"] == "preflight_passed_runtime_not_authorized"
    assert receipt["execution_controls"]["canary_started"] is False
    assert receipt["execution_controls"]["tracer_started"] is False
    assert receipt["scope"]["runtime_execution_authorized"] is False
    expected = json.dumps(authorization, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    assert receipt["authorization_binding"]["sha256"] == hashlib.sha256(expected).hexdigest()
    assert not (tmp_path / "new-output").exists()


def test_terminal_receipt_write_failure_leaves_consumed_started_receipt(tmp_path, monkeypatch):
    authorization, lab = _authorization(tmp_path)
    scope = tmp_path / "scope"
    scope.mkdir()

    def fail_finalize(*_args):
        raise OSError("simulated final receipt storage failure")

    monkeypatch.setattr(preflight, "_finalize_receipt", fail_finalize)
    with pytest.raises(OSError, match="storage failure"):
        preflight.run_preflight(
            authorization, scope_dir=scope, output_dir=tmp_path / "new-output", lab=lab,
            resource_probe=lambda: _environment(load=9.0),
        )

    started = json.loads((scope / "preflight-receipt.json").read_text())
    assert started["status"] == "preflight_started_no_runtime_authorization"
    assert started["terminal_receipt_pending"] is True
    with pytest.raises(FileExistsError, match="already consumed"):
        preflight.run_preflight(
            authorization, scope_dir=scope, output_dir=tmp_path / "new-output", lab=lab,
            resource_probe=lambda: _environment(),
        )


def test_source_hash_mismatch_never_opens_hdf5(tmp_path, monkeypatch):
    source = tmp_path / "trajectory.h5"
    source.write_bytes(b"x")
    monkeypatch.setattr(preflight, "LAB", tmp_path)
    monkeypatch.setattr(preflight, "SOURCE_BYTES", 1)
    monkeypatch.setattr(preflight, "SOURCE_SHA256", "expected-hash")
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "1")
    monkeypatch.setenv("MKL_NUM_THREADS", "1")
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")
    authorization, _lab = _authorization(tmp_path / "auth")
    authorization["preflight_contract"]["source"].update(bytes=1, sha256="expected-hash")
    opened = []

    monkeypatch.setattr(preflight, "_sha256_stream", lambda _stream: "wrong-hash")
    monkeypatch.setattr(preflight, "_unused_h5py", None, raising=False)

    import h5py

    monkeypatch.setattr(h5py, "File", lambda *_a, **_kw: opened.append(True))
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        preflight.input_preflight(authorization, source=source)
    assert not opened


def test_source_symlink_is_rejected_before_hdf5_open(tmp_path, monkeypatch):
    target = tmp_path / "real-bytes.bin"
    target.write_bytes(b"x")
    source = tmp_path / "trajectory.h5"
    source.symlink_to(target)
    monkeypatch.setattr(preflight, "SOURCE_BYTES", 1)
    monkeypatch.setattr(preflight, "SOURCE_SHA256", "matched-hash")
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "1")
    monkeypatch.setenv("MKL_NUM_THREADS", "1")
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")
    authorization, _lab = _authorization(tmp_path / "auth")
    authorization["preflight_contract"]["source"].update(bytes=1, sha256="matched-hash")
    opened = []

    import h5py
    monkeypatch.setattr(h5py, "File", lambda *_a, **_kw: opened.append(True))
    with pytest.raises(OSError):
        preflight.input_preflight(authorization, source=source)
    assert not opened


def test_path_replacement_after_open_cannot_redirect_hdf5_read(tmp_path, monkeypatch):
    source = tmp_path / "trajectory.h5"
    source.write_bytes(b"verified")
    original_inode = source.stat().st_ino
    monkeypatch.setattr(preflight, "LAB", tmp_path)
    monkeypatch.setattr(preflight, "SOURCE_BYTES", len(b"verified"))
    monkeypatch.setattr(preflight, "SOURCE_SHA256", "matched-hash")
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "1")
    monkeypatch.setenv("MKL_NUM_THREADS", "1")
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")
    authorization, _lab = _authorization(tmp_path / "auth")
    authorization["preflight_contract"]["source"].update(
        bytes=len(b"verified"), sha256="matched-hash"
    )
    calls = []

    def fake_hash(stream):
        calls.append("hash")
        stream.seek(0)
        assert stream.read() == b"verified"
        stream.seek(0)
        return "matched-hash"

    class Dataset:
        def __init__(self, shape):
            self.shape = shape

        def __getitem__(self, _index):
            return np.linspace(0.0, 0.164, 42)

    class Handle:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            return iter(("time", "position", "velocity", "valid", "particle_zone"))

        def __getitem__(self, name):
            shapes = {
                "time": (1086,),
                "position": (1086, 217485, 3),
                "velocity": (1086, 217485, 3),
                "valid": (1086, 217485),
                "particle_zone": (217485,),
            }
            return Dataset(shapes[name])

    def open_h5(stream, mode):
        assert mode == "r"
        calls.append("hdf5-open")
        assert os.fstat(stream.fileno()).st_ino == original_inode
        source.rename(tmp_path / "renamed-original.h5")
        source.write_bytes(b"replacement")
        stream.seek(0)
        assert stream.read() == b"verified"
        stream.seek(0)
        return Handle()

    monkeypatch.setattr(preflight, "_sha256_stream", fake_hash)
    import h5py
    monkeypatch.setattr(h5py, "File", open_h5)
    with pytest.raises(ValueError, match="source changed during read-only metadata validation"):
        preflight.input_preflight(authorization, source=source)

    assert calls == ["hash", "hdf5-open"]
    assert source.read_bytes() == b"replacement"


def test_same_size_in_place_change_with_restored_mtime_is_detected_by_ctime(tmp_path, monkeypatch):
    source = tmp_path / "trajectory.h5"
    source.write_bytes(b"verified")
    monkeypatch.setattr(preflight, "LAB", tmp_path)
    monkeypatch.setattr(preflight, "SOURCE_BYTES", len(b"verified"))
    monkeypatch.setattr(preflight, "SOURCE_SHA256", "matched-hash")
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "1")
    monkeypatch.setenv("MKL_NUM_THREADS", "1")
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")
    authorization, _lab = _authorization(tmp_path / "auth")
    authorization["preflight_contract"]["source"].update(
        bytes=len(b"verified"), sha256="matched-hash"
    )

    class Dataset:
        def __init__(self, shape):
            self.shape = shape

        def __getitem__(self, _index):
            return np.linspace(0.0, 0.164, 42)

    class Handle:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            return iter(("time", "position", "velocity", "valid", "particle_zone"))

        def __getitem__(self, name):
            shapes = {
                "time": (1086,),
                "position": (1086, 217485, 3),
                "velocity": (1086, 217485, 3),
                "valid": (1086, 217485),
                "particle_zone": (217485,),
            }
            return Dataset(shapes[name])

    def mutate_in_place(stream, mode):
        assert mode == "r"
        before = os.fstat(stream.fileno())
        with source.open("r+b") as writer:
            writer.write(b"mutated!")
            writer.flush()
            os.fsync(writer.fileno())
        os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
        after = os.fstat(stream.fileno())
        assert after.st_size == before.st_size
        assert after.st_mtime_ns == before.st_mtime_ns
        assert after.st_ctime_ns != before.st_ctime_ns
        return Handle()

    monkeypatch.setattr(preflight, "_sha256_stream", lambda _stream: "matched-hash")
    import h5py
    monkeypatch.setattr(h5py, "File", mutate_in_place)
    with pytest.raises(ValueError, match="source changed during read-only metadata validation"):
        preflight.input_preflight(authorization, source=source)


def test_module_import_does_not_mutate_thread_or_gpu_environment(monkeypatch):
    sentinels = {
        "OMP_NUM_THREADS": "31",
        "OPENBLAS_NUM_THREADS": "37",
        "MKL_NUM_THREADS": "41",
        "CUDA_VISIBLE_DEVICES": "codex-import-side-effect-test",
    }
    for name, value in sentinels.items():
        monkeypatch.setenv(name, value)
    before = {name: os.environ.get(name) for name in sentinels}
    importlib.reload(preflight)
    after = {name: os.environ.get(name) for name in sentinels}
    assert after == before


def test_preflight_module_has_no_tracer_execution_entrypoint():
    tree = ast.parse(Path(preflight.__file__).read_text(encoding="utf-8"))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    from_imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "scripts.f4_tallwall120_material" not in from_imports
    assert "f4_tallwall120_material" not in imports
    assert "trace_tallwall120" not in calls
