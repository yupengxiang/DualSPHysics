"""Source-only tests for V54's actual overlay-worker module parent."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_portable_executor_v54.py"
V53_REQUEST = ROOT / (
    "campaigns/ds-data-02/stage2/native-reconstruction/"
    "raw-to-label-v53-root140-source-prepared-20261009/"
    "f2-s1-root140-v53-executor-request.json")


def _load():
    spec = importlib.util.spec_from_file_location("v54_worker_parent_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


B = _load()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_four_module_aliases_are_materialized_beside_overlay_worker(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle-target"
    worker_parent = bundle / "sources"
    runtime = bundle / "runtime" / "runtime" / "native"
    worker_parent.mkdir(parents=True)
    runtime.mkdir(parents=True)
    bindings = {}
    for role, filename in B.MODULE_NAMES.items():
        source = runtime / filename
        source.write_bytes((role + "\n").encode("ascii"))
        bindings[role] = {"path": str(source), "sha256": _sha(source),
                          "bytes": source.stat().st_size}
    records = B._materialize_aliases_in_worker_parent(bindings, worker_parent)
    assert {row["role"] for row in records} == set(B.MODULE_NAMES)
    assert all(Path(row["alias_path"]).parent == worker_parent for row in records)
    assert all(row["inode_distinct"] for row in records)
    assert all(row["source_fallback"] == "FORBIDDEN" for row in records)
    assert all((worker_parent / filename).is_file() for filename in B.MODULE_NAMES.values())


def test_module_alias_rejects_worktree_path_outside_copied_bundle(tmp_path: Path) -> None:
    worker_parent = tmp_path / "bundle-target" / "sources"
    worker_parent.mkdir(parents=True)
    outside = tmp_path / "outside-v14.py"
    outside.write_text("# outside\n", encoding="utf-8")
    bindings = {
        "raw_converter": {"path": str(outside), "sha256": _sha(outside), "bytes": outside.stat().st_size},
    }
    with pytest.raises(B.PortableV54Error, match="outside the copied bundle"):
        B._materialize_aliases_in_worker_parent(bindings, worker_parent)


def test_four_module_private_venv_import_smoke_uses_only_worker_aliases(tmp_path: Path) -> None:
    """Exercise the actual isolated import path without any scientific payload."""
    bundle = tmp_path / "bundle-target"
    worker_parent = bundle / "sources"
    runtime = bundle / "runtime" / "runtime" / "native"
    worker_parent.mkdir(parents=True)
    runtime.mkdir(parents=True)
    contents = {
        "raw_converter": "VALUE = 'converter'\n",
        "v14_operator": "VALUE = 'v14'\n",
        "v15_operator": (
            "import ds_data02_stage2_f2_replay_v14 as v14\n"
            "VALUE = v14.VALUE\n"),
        "v16_operator": (
            "import ds_data02_stage2_f2_replay_v15 as v15\n"
            "VALUE = v15.VALUE\n"),
    }
    bindings = {}
    for role, filename in B.MODULE_NAMES.items():
        source = runtime / filename
        source.write_text(contents[role], encoding="utf-8")
        bindings[role] = {
            "path": str(source), "sha256": _sha(source),
            "bytes": source.stat().st_size,
        }
    records = B._materialize_aliases_in_worker_parent(bindings, worker_parent)
    result = B._import_four_modules(
        "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python",
        records)
    assert result["all_four_modules_colocated"] is True
    assert result["sys_path0"].startswith("/tmp/ds02-v54-import-")
    assert {Path(result[key]).name for key in ("raw_converter", "v14", "v15", "v16")} == set(
        B.MODULE_NAMES.values())
    assert all(Path(result[key]).is_relative_to(Path(result["sys_path0"]))
               for key in ("raw_converter", "v14", "v15", "v16"))


def test_build_forward_records_overlay_worker_parent_and_four_roles(tmp_path: Path) -> None:
    output = tmp_path / "v54-request.json"
    result = B.build_forward(
        v53_request=V53_REQUEST,
        target_root=tmp_path / "fresh" / "bundle-target",
        output_root=tmp_path / "fresh" / "products",
        output_request=output)
    value = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "READY_FOR_PARENT_STAGE2_GUARD"
    assert value["forward_v54"]["worker_parent_relative_directory"] == "sources"
    assert value["forward_v54"]["worker_role"] == "v2_worker"
    assert value["forward_v54"]["module_binding_roles"] == [
        "raw_converter", "v14_operator", "v15_operator", "v16_operator"]
    assert value["execution"]["command"][3].endswith(
        "runtime/runtime/executor/ds_data02_stage2_f2_portable_executor_v54.py")
    assert value["execution"]["evaluator_command"][3].endswith(
        "runtime/runtime/executor/ds_data02_stage2_f2_portable_executor_v34.py")
    assert str(value["execution"]["evaluator_command"][3]).startswith(str(tmp_path / "fresh"))
    assert value["execution"]["evaluator_executor_role"] == "executor_v34"
    assert value["execution"]["module_alias_policy"].startswith("four V52")
    assert value["raw_opened"] is False and value["hdf5_opened"] is False
    assert value["qualification"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    assert not (tmp_path / "fresh" / "bundle-target").exists()
