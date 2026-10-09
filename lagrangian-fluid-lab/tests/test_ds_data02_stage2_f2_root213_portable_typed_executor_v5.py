"""ROOT230 V5 recursive nested metadata closure tests.

These tests exercise the real V2 request rewriter and the copied V5 runtime
view helper with bounded JSON fixtures.  They never open production HDF5,
BI4, native frames, or the deferred V16 result.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
EXECUTOR_SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_root213_portable_typed_executor_v5.py"
RUNTIME_SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_typed_only_portable_rebind_v5.py"
ROOT228_SEMANTIC_SIDECAR = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/"
    "STAGE2_F2_ROOT213_PORTABLE_TYPED_PARENT_ROOT228_V4/"
    "f2-s1-root213-root228-portable-typed-parent-root-forward-030-001/"
    "portable/evidence/v12/semantic-sidecar.json"
)


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _Table:
    """Small table with the same source/target uniqueness API as V1."""

    def __init__(self, root: Path, source: Path):
        self.output_root = root
        self.items: list[dict] = []
        self.by_source: dict[str, dict] = {}
        self.by_target: dict[str, dict] = {}
        stat = source.stat()
        self.add(
            role="root200_inner_request",
            source=source,
            target="evidence/root.json",
            sha256=_sha(source),
            stat={"bytes": stat.st_size, "mode_bits": stat.st_mode & 0o7777,
                  "mtime_ns": stat.st_mtime_ns},
            kind="bounded_nested_metadata", deferred=False,
        )

    def add(self, *, role, source, target, sha256, stat, kind, deferred,
            placeholder=False, executable_exception=False):
        key = str(Path(source).absolute())
        if key in self.by_source:
            return self.by_source[key]
        value = {
            "logical_role": role, "source_kind": kind, "actionable": True,
            "source_sha256": sha256, "source_stat_provenance": dict(stat or {}),
            "source_path_provenance": key, "target_relative_path": target,
            "deferred_content": deferred, "placeholder_only": placeholder,
            "executable_environment_exception": executable_exception,
        }
        self.items.append(value)
        self.by_source[key] = value
        self.by_target[target] = value
        return value

    def get(self, source: Path):
        return self.by_source.get(str(Path(source).absolute()))


def test_root228_sidecar_historical_path_is_actionable():
    module = _load(EXECUTOR_SCRIPT, "root213_executor_v5_real_sidecar_test")
    if not ROOT228_SEMANTIC_SIDECAR.is_file():
        pytest.skip("ROOT228 small semantic sidecar is not available")
    value = json.loads(ROOT228_SEMANTIC_SIDECAR.read_text(encoding="utf-8"))
    records = module._strict_path_records_v5(value)
    pointers = {record[2] for record in records}
    assert ("historical_provenance", "root194_sidecar", "path") in pointers
    assert ("historical_provenance", "root194_request", "path") in pointers


def test_recursive_collect_and_real_v2_rewrite_close_nested_historical_graph(tmp_path: Path):
    module = _load(EXECUTOR_SCRIPT, "root213_executor_v5_recursive_graph_test")
    source = tmp_path / "source"
    relocated = tmp_path / "relocated"
    source.mkdir()
    relocated.mkdir()
    child = source / "child.json"
    grandchild = source / "grandchild.json"
    grandchild.write_text(json.dumps({"value": 7}, sort_keys=True) + "\n")
    child.write_text(json.dumps({
        "historical_provenance": {"grandchild": {"path": str(grandchild)}}
    }, sort_keys=True) + "\n")
    parent = source / "parent.json"
    parent.write_text(json.dumps({
        "historical_provenance": {"child": {"path": str(child)}}
    }, sort_keys=True) + "\n")

    table = _Table(relocated, parent)
    module._install_hooks()
    try:
        discoveries = module._collect_recursive_metadata(table)
        assert {item["source_path"] for item in discoveries} == {str(child), str(grandchild)}
        checks = module._preflight_recursive_rewrites(table, relocated)
        assert checks and all(item["status"] == "PASS_REWRITE_PREFLIGHT" for item in checks)
    finally:
        module._restore_hooks()

    runtime = _load(RUNTIME_SCRIPT, "root213_runtime_v5_recursive_graph_test")
    child_role = table.get(child)
    source_map = {
        str(child): (child_role, relocated / child_role["target_relative_path"]),
        str(grandchild): (table.get(grandchild),
                          relocated / table.get(grandchild)["target_relative_path"]),
    }
    target, value, _ = runtime._recursive_rebase(
        parent, root=relocated, source_map=source_map, label="sidecar")
    assert target.is_file()
    rebound = value["historical_provenance"]["child"]["path"]
    assert rebound.startswith(str(relocated))
    assert Path(rebound).is_file()
    nested = json.loads(Path(rebound).read_text(encoding="utf-8"))
    assert nested["historical_provenance"]["grandchild"]["path"].startswith(str(relocated))


def test_recursive_rewrite_rejects_unknown_nested_absolute_path(tmp_path: Path):
    runtime = _load(RUNTIME_SCRIPT, "root213_runtime_v5_unknown_path_test")
    source = tmp_path / "source"
    root = tmp_path / "relocated"
    source.mkdir()
    root.mkdir()
    parent = source / "parent.json"
    parent.write_text(json.dumps({
        "historical_provenance": {"missing": {"path": str(source / "missing.json")}}
    }) + "\n")
    with pytest.raises(runtime.V2.PortableRebindV2Error, match="unbound actionable"):
        runtime._recursive_rebase(parent, root=root, source_map={}, label="sidecar")


def test_recursive_rewrite_binds_worker_scratch_directory_anchors(tmp_path: Path):
    runtime = _load(RUNTIME_SCRIPT, "root213_runtime_v5_directory_alias_test")
    source = tmp_path / "source"
    root = tmp_path / "relocated"
    source.mkdir()
    root.mkdir()
    parent = source / "worker-request.json"
    parent.write_text(json.dumps({
        "runtime": {"scratch": {"root": "/old/decoder-scratch"}},
        "v64_raw_scope": {"root": "/old/raw-bundle"},
    }) + "\n")
    original = runtime.V2._directory_rebind
    runtime.V2._directory_rebind = runtime._directory_rebind_v5
    try:
        _target, value, _ = runtime._recursive_rebase(
            parent, root=root, source_map={}, label="worker")
    finally:
        runtime.V2._directory_rebind = original
    assert value["runtime"]["scratch"]["root"] == str(root / "runtime" / "scratch")
    assert value["v64_raw_scope"]["root"] == str(root / "evidence" / "raw-scope")


def test_v5_runtime_entrypoint_has_frozen_v2_sibling():
    module = _load(RUNTIME_SCRIPT, "root213_runtime_v5_sibling_test")
    assert module.V2_PATH.name == "ds_data02_stage2_f2_typed_only_portable_rebind_v2.py"
    assert module.V2_PATH.is_file()
