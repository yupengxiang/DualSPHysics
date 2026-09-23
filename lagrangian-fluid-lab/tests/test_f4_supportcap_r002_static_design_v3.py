from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import f4_supportcap_r002_static_design_v2 as predecessor
from scripts import f4_supportcap_r002_static_design_v3 as design


_BINARY_SUFFIXES = {".h5", ".hdf5", ".npz"}
_PATH_ACCESSORS = (
    "stat", "lstat", "resolve", "exists", "is_file", "is_symlink",
    "open", "read_bytes", "read_text",
)


def test_build_recipe_never_accesses_hdf5_or_npz_paths(monkeypatch):
    original_hash = predecessor.predecessor._sha256

    def guard_path_accessor(method_name, original):
        def guarded(path, *args, **kwargs):
            path = Path(path)
            if path.suffix.lower() in _BINARY_SUFFIXES:
                pytest.fail(f"static receipt builder called {method_name} on binary path {path}")
            return original(path, *args, **kwargs)
        return guarded

    for method_name in _PATH_ACCESSORS:
        monkeypatch.setattr(
            Path, method_name,
            guard_path_accessor(method_name, getattr(Path, method_name)),
        )

    def guarded_hash(path):
        path = Path(path)
        if path.suffix.lower() in _BINARY_SUFFIXES:
            pytest.fail(f"static receipt builder hashed binary path {path}")
        return original_hash(path)

    monkeypatch.setattr(predecessor.predecessor, "_sha256", guarded_hash)
    recipe = design.build_recipe()
    assert recipe["static_read_boundary"]["hdf5_npz_stat_open_parse_or_hash_performed"] is False


def test_v3_receipt_binds_access_guard_generator_and_tests():
    recipe = json.loads((design.LAB / design.RECEIPT).read_text(encoding="utf-8"))
    assert recipe == design.build_recipe()
    bindings = {item["path"]: item for item in recipe["bindings"]}
    assert "scripts/f4_supportcap_r002_static_design_v3.py" in bindings
    assert "tests/test_f4_supportcap_r002_static_design_v3.py" in bindings
    assert recipe["schema"] == design.SCHEMA
    assert recipe["static_read_boundary"]["forbidden_path_operations_on_hdf5_npz"] == [
        "stat", "lstat", "resolve", "exists", "is_file", "is_symlink",
        "open", "read_bytes", "read_text", "hash",
    ]
    authority = recipe["execution_authority"]
    for key in (
        "native_preflight_authorized", "cpu_canary_authorized", "solver_authorized",
        "gpu_authorized", "worker_or_queue_authorized",
    ):
        assert authority[key] is False
    assert authority["static_design_authorized"] is True
    assert recipe["execution_authority"]["qualification_credit"] == 0


def test_written_v3_receipt_closes_text_sources_and_inherits_trace_hash_only():
    receipt = json.loads((design.LAB / design.RECEIPT).read_text(encoding="utf-8"))
    attribution = json.loads(
        predecessor.predecessor.ATTRIBUTION.read_text(encoding="utf-8")
    )
    inherited = {item["path"]: item for item in attribution["bindings"]}
    for binding in receipt["bindings"]:
        source = design.LAB / binding["path"]
        if source.suffix.lower() in _BINARY_SUFFIXES:
            assert binding == inherited[binding["path"]]
            continue
        assert source.stat().st_size == binding["bytes"]
        assert hashlib.sha256(source.read_bytes()).hexdigest() == binding["sha256"]
