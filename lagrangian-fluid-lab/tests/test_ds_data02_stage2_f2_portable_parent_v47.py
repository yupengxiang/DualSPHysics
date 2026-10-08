from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "ds_data02_stage2_f2_portable_parent_v47.py"
spec = importlib.util.spec_from_file_location("parent_v47_under_test", SCRIPT)
assert spec is not None and spec.loader is not None
V47 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V47)

ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
ROOT_V46_PARENT = ROOT / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/native-reconstruction/"
    "raw-to-label-v46-parent-closure-root-082/"
    "f2-s1-portable-parent-request-v46-root-082.json"
)
ROOT_V34 = ROOT / "lagrangian-fluid-lab/scripts/ds_data02_stage2_f2_portable_executor_v34.py"
ROOT_PARENT_V3 = ROOT / (
    "lagrangian-fluid-lab/scripts/ds_data02_stage2_f2_portable_executor_parent_v3.py"
)


def _load(name: str, path: Path):
    module_spec = importlib.util.spec_from_file_location(name, path)
    assert module_spec is not None and module_spec.loader is not None
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(not ROOT_V46_PARENT.is_file(), reason="root V46 metadata fixture is not present")
def test_forward_real_v46_normalizes_overlay_without_changing_target_paths(tmp_path: Path) -> None:
    before = V47.sha256_file(ROOT_V46_PARENT)
    executor = tmp_path / "executor-v47.json"
    parent = tmp_path / "parent-v47.json"
    target = tmp_path / "fresh-target"
    products = tmp_path / "fresh-products"
    result = V47.forward_parent(
        base_parent=ROOT_V46_PARENT,
        executor_output=executor,
        parent_output=parent,
        target_root=target,
        output_root=products,
        parent_attempt_id="f2-s1-v47-test-001",
        home_receipt_path=tmp_path / "home-receipt.json",
        supervisor_output_root=tmp_path / "supervisor",
    )
    assert V47.sha256_file(ROOT_V46_PARENT) == before
    old_parent = json.loads(ROOT_V46_PARENT.read_text(encoding="utf-8"))
    old_executor = json.loads(Path(old_parent["executor_request"]["path"]).read_text(encoding="utf-8"))
    value = json.loads(executor.read_text(encoding="utf-8"))
    forwarded = json.loads(parent.read_text(encoding="utf-8"))

    assert result["status"] == "READY_FOR_PARENT_GUARD_V47_PATH_NORMALIZATION"
    assert value["schema"] == V47.EXECUTOR_SCHEMA
    assert value["sha256"] == V47.canonical_sha(value)
    assert Path(value["v5_overlay_template"]["path"]).is_absolute()
    assert value["v5_overlay_template"]["sha256"] == old_executor["v5_overlay_template"]["sha256"]
    assert value["v5_overlay_template"]["canonical_sha256"] == old_executor["v5_overlay_template"]["canonical_sha256"]
    assert V47._target_relative_paths(value) == V47._target_relative_paths(old_executor)
    assert forwarded["sha256"] == V47.canonical_sha(forwarded)
    assert forwarded["executor_request"]["path"] == str(executor)
    assert forwarded["executor_request"]["sha256"] == V47.sha256_file(executor)
    assert forwarded["qualification"] == V47.UNKNOWN
    assert forwarded["parent_resource_binding"]["allow_missing_parent"] is True
    assert any(row.get("role") == "parent_closure_builder_v47"
               for row in forwarded["static_bindings"])


@pytest.mark.skipif(not ROOT_V46_PARENT.is_file(), reason="root V46 metadata fixture is not present")
def test_v34_and_parent_v3_load_the_normalized_metadata_only_request(tmp_path: Path) -> None:
    executor = tmp_path / "executor-v47.json"
    parent = tmp_path / "parent-v47.json"
    external_probe = Path("/var/tmp/ds02-stage2") / ("v47-test-" + tmp_path.name)
    V47.forward_parent(
        base_parent=ROOT_V46_PARENT,
        executor_output=executor,
        parent_output=parent,
        target_root=external_probe / "fresh-target",
        output_root=external_probe / "fresh-products",
        parent_attempt_id="f2-s1-v47-test-002",
        home_receipt_path=tmp_path / "home-receipt.json",
        # Parent V3 requires the supervisor namespace to be external-FS bound;
        # this remains a metadata-only probe and does not create the namespace.
        supervisor_output_root=Path("/var/tmp/ds02-stage2") / ("v47-test-" + tmp_path.name) / "supervisor",
    )
    v34 = _load("root_v34_for_v47_test", ROOT_V34)
    loaded = v34._load_request(executor)
    assert loaded["schema"] == V47.EXECUTOR_SCHEMA
    parent_v3 = _load("root_parent_v3_for_v47_test", ROOT_PARENT_V3)
    checked = parent_v3._validate_request(parent, verify_static_content=False)
    assert checked["request"]["schema"] == V47.SCHEMA
    assert checked["request"]["status"] == "READY_FOR_PARENT_GUARD"


@pytest.mark.skipif(not ROOT_V46_PARENT.is_file(), reason="root V46 metadata fixture is not present")
def test_v47_rejects_existing_namespace_and_preserves_source_binding(tmp_path: Path) -> None:
    target = tmp_path / "already-there"
    target.mkdir()
    with pytest.raises(V47.ParentV47Error, match="fresh and distinct"):
        V47.forward_parent(
            base_parent=ROOT_V46_PARENT,
            executor_output=tmp_path / "executor-v47.json",
            parent_output=tmp_path / "parent-v47.json",
            target_root=target,
            output_root=tmp_path / "fresh-products",
            parent_attempt_id="f2-s1-v47-test-003",
            home_receipt_path=tmp_path / "home-receipt.json",
            supervisor_output_root=tmp_path / "supervisor",
        )
