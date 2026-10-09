"""Source-only tests for V55 worker identity, namespace rebasing, and timeout."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_portable_executor_v55.py"
V54_REQUEST = ROOT / (
    "campaigns/ds-data-02/stage2/native-reconstruction/"
    "raw-to-label-v54-root145-source-prepared-20261009/"
    "f2-s1-root145-v54b-executor-request.json")


def _load():
    spec = importlib.util.spec_from_file_location("v55_strict_worker_alias_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


B = _load()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bindings(tmp_path: Path, *, sleepy: bool = False):
    bundle = tmp_path / "bundle-target"
    worker_parent = bundle / "sources"
    runtime = bundle / "runtime" / "runtime" / "native"
    worker_parent.mkdir(parents=True)
    runtime.mkdir(parents=True)
    contents = {
        "raw_converter": ("import time\ntime.sleep(2)\n" if sleepy else "") + "VALUE='raw'\n",
        "v14_operator": "VALUE='v14'\n",
        "v15_operator": "import ds_data02_stage2_f2_replay_v14 as v14\nVALUE=v14.VALUE\n",
        "v16_operator": "import ds_data02_stage2_f2_replay_v15 as v15\nVALUE=v15.VALUE\n",
    }
    bindings = {}
    for role, filename in B.MODULE_NAMES.items():
        source = runtime / filename
        source.write_text(contents[role], encoding="utf-8")
        bindings[role] = {"path": str(source), "sha256": _sha(source),
                          "bytes": source.stat().st_size}
    return bundle, worker_parent, runtime, bindings


def test_aliases_record_real_device_inode_and_mode(tmp_path: Path) -> None:
    bundle, worker_parent, runtime, bindings = _bindings(tmp_path)
    records = B._materialize_aliases_in_worker_parent(bindings, worker_parent)
    assert all(row["inode_distinct"] is True for row in records)
    for row in records:
        source = Path(row["copied_source_path"]).stat(follow_symlinks=False)
        alias = Path(row["alias_path"]).stat(follow_symlinks=False)
        assert (source.st_dev, source.st_ino) != (alias.st_dev, alias.st_ino)
        assert row["source_mode_bits"] == row["alias_mode_bits"]
        assert Path(row["alias_path"]).is_relative_to(worker_parent)
    assert (bundle / "sources").is_dir()


def test_existing_hardlink_alias_is_rejected(tmp_path: Path) -> None:
    _bundle, worker_parent, _runtime, bindings = _bindings(tmp_path)
    first = bindings["raw_converter"]
    os.link(first["path"], worker_parent / B.MODULE_NAMES["raw_converter"])
    with pytest.raises(B.PortableV55Error, match="shares source inode"):
        B._materialize_aliases_in_worker_parent(bindings, worker_parent)


def test_existing_mode_drift_is_rejected(tmp_path: Path) -> None:
    _bundle, worker_parent, _runtime, bindings = _bindings(tmp_path)
    first = bindings["raw_converter"]
    alias = worker_parent / B.MODULE_NAMES["raw_converter"]
    alias.write_bytes(Path(first["path"]).read_bytes())
    alias.chmod(0o600)
    with pytest.raises(B.PortableV55Error, match="mode differs"):
        B._materialize_aliases_in_worker_parent(bindings, worker_parent)


def test_private_import_smoke_is_bounded_and_uses_owned_scratch(tmp_path: Path) -> None:
    _bundle, worker_parent, _runtime, bindings = _bindings(tmp_path)
    records = B._materialize_aliases_in_worker_parent(bindings, worker_parent)
    result = B._import_four_modules(
        "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python", records)
    scratch = Path(result["scratch_root"])
    assert result["timeout_seconds"] == B.IMPORT_TIMEOUT_SECONDS
    assert scratch.parent == worker_parent.parent
    assert result["sys_path0"].startswith(str(scratch))
    assert all(Path(result[key]).is_relative_to(Path(result["sys_path0"]))
               for key in ("raw_converter", "v14", "v15", "v16"))


def test_private_import_timeout_fails_closed(tmp_path: Path) -> None:
    _bundle, worker_parent, _runtime, bindings = _bindings(tmp_path, sleepy=True)
    records = B._materialize_aliases_in_worker_parent(bindings, worker_parent)
    old_timeout = B.IMPORT_TIMEOUT_SECONDS
    B.IMPORT_TIMEOUT_SECONDS = 0.05
    try:
        with pytest.raises(B.PortableV55Error, match="timed out"):
            B._import_four_modules(
                "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python",
                records)
    finally:
        B.IMPORT_TIMEOUT_SECONDS = old_timeout


def test_build_rebases_all_actionable_namespace_paths(tmp_path: Path) -> None:
    output = tmp_path / "v55-request.json"
    target = tmp_path / "fresh" / "bundle-target"
    products = tmp_path / "fresh" / "products"
    result = B.build_forward(v54_request=V54_REQUEST, target_root=target,
                             output_root=products, output_request=output)
    value = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "READY_FOR_PARENT_STAGE2_GUARD"
    assert value["forward_v55"]["alias_identity_check"].startswith("st_dev")
    assert value["forward_v55"]["private_import_timeout_seconds"] == 60.0
    assert value["execution"]["runtime_target_root"] == str(target / "runtime")
    assert value["storage_scope"]["external_output_root"] == str(products)
    assert value["storage_scope"]["supervisor_output_root"].startswith(str(products.parent))
    assert value["parent_resource_binding"]["attempt_id"].startswith("f2-s1-root145-v55")
    assert value["execution"]["command"][3].startswith(str(target))
    assert value["execution"]["evaluator_command"][3].startswith(str(target))
    assert all(str(row["target_path"]).startswith(str(target))
               for row in value["runtime_sources"])
    # Historical ROOT140/V54 paths may remain only in provenance records; no
    # actionable fresh namespace may silently point at the consumed target.
    actionable = [
        value["execution"]["runtime_target_root"],
        value["storage_scope"]["external_output_root"],
        value["storage_scope"]["supervisor_output_root"],
        value["storage_scope"]["parent_attempt_id"],
        *value["execution"]["command"],
        *value["execution"]["evaluator_command"],
        *(row["target_path"] for row in value["runtime_sources"]),
    ]
    assert all("ROOT140" not in str(item) and "ROOT140_V53" not in str(item)
               for item in actionable)
    assert not target.exists() and not products.exists()
    assert value["sha256"] == B.canonical_sha(value)
