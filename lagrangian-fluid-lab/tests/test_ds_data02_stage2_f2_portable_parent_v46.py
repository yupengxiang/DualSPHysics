from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "ds_data02_stage2_f2_portable_parent_v46.py"
spec = importlib.util.spec_from_file_location("parent_v46_under_test", SCRIPT)
assert spec is not None and spec.loader is not None
V46 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V46)

ROOT_V45_PARENT = Path(
    "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/native-reconstruction/"
    "raw-to-label-v45-full-chain-root-082/f2-s1-portable-parent-request-v45-root-082.json"
)
ROOT_V45_EXECUTOR = Path(
    "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/native-reconstruction/"
    "raw-to-label-v45-full-chain-root-082/f2-s1-portable-executor-request-v45-root-082.json"
)
ROOT_V45_SCRIPT = Path(
    "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
    "lagrangian-fluid-lab/scripts/ds_data02_stage2_f2_portable_executor_v45.py"
)


@pytest.mark.skipif(not ROOT_V45_PARENT.is_file(), reason="root V45 metadata fixture is not present")
def test_forward_real_v45_parent_adds_direct_runtime_and_literal_python_closure(tmp_path: Path) -> None:
    output = tmp_path / "parent-v46.json"
    result = V46.forward_parent(
        base_request=ROOT_V45_PARENT,
        output=output,
        parent_attempt_id="f2-s1-portable-v46-test-001",
    )

    value = json.loads(output.read_text(encoding="utf-8"))
    assert value["status"] == "READY_FOR_PARENT_GUARD"
    assert value["sha256"] == V46.canonical_sha(value)
    assert result["h5_bi4_raw_result_payload_read"] is False
    assert value["v46_static_closure"]["schema"] == V46.FORWARD_SCHEMA
    roles = {item["role"]: item for item in value["static_bindings"]}
    for role in (
        "parent_executor_v3", "shared_v21_accounting", "shared_runtime_v6",
        "runtime_v2", "executor_v45", "executor_v41_compat",
        "executor_v43_builder", "executor_v38_compat", "executor_v34_compat",
        "executor_v34_request", "os_strace", "python_executable",
    ):
        assert role in roles
        assert len(roles[role]["sha256"]) == 64
    python = roles["python_executable"]
    assert python["path"].endswith("/lagrangian-fluid-lab/.venv/bin/python")
    assert python["invocation_path"] == python["path"]
    assert python["path"] != python["resolved_path_provenance"]
    assert value["parent_resource_binding"]["allow_missing_parent"] is True
    assert value["accounting"]["same_parent_ledger"] is True
    assert value["qualification"] == V46.UNKNOWN


@pytest.mark.skipif(not ROOT_V45_PARENT.is_file(), reason="root V45 metadata fixture is not present")
def test_forward_refuses_nonfresh_or_existing_output_and_bad_base(tmp_path: Path) -> None:
    output = tmp_path / "parent-v46.json"
    V46.forward_parent(
        base_request=ROOT_V45_PARENT,
        output=output,
        parent_attempt_id="f2-s1-portable-v46-test-002",
    )
    with pytest.raises(V46.ParentV46Error, match="existing output"):
        V46.forward_parent(
            base_request=ROOT_V45_PARENT,
            output=output,
            parent_attempt_id="f2-s1-portable-v46-test-003",
        )

    malformed = tmp_path / "bad-base.json"
    value = json.loads(ROOT_V45_PARENT.read_text(encoding="utf-8"))
    value["execution"]["closed_executor_command"][0] = "/usr/bin/python3"
    value["sha256"] = V46.canonical_sha(value)
    malformed.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(V46.ParentV46Error, match="approved literal venv"):
        V46.forward_parent(
            base_request=malformed,
            output=tmp_path / "bad-out.json",
            parent_attempt_id="f2-s1-portable-v46-test-004",
        )


@pytest.mark.skipif(
    not ROOT_V45_PARENT.is_file() or not ROOT_V45_EXECUTOR.is_file() or not ROOT_V45_SCRIPT.is_file(),
    reason="root V45 build inputs are not present",
)
def test_overlay_consumes_a_real_v45_build_parent_result(tmp_path: Path) -> None:
    """Exercise V45's real metadata builder before applying the V46 overlay."""
    root_spec = importlib.util.spec_from_file_location("root_v45_builder_for_v46_test", ROOT_V45_SCRIPT)
    assert root_spec is not None and root_spec.loader is not None
    root_v45 = importlib.util.module_from_spec(root_spec)
    root_spec.loader.exec_module(root_v45)
    parent = tmp_path / "v45-built-parent.json"
    result = root_v45.build_parent(
        executor_request=ROOT_V45_EXECUTOR,
        output=parent,
        external_filesystem=Path("/var/tmp/ds02-stage2"),
        ledger_path=Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/resource-ledger.json"),
        parent_attempt_id="f2-s1-v46-real-builder-test-001",
        max_wall_seconds=60.0,
        home_receipt_path=tmp_path / "home-receipt.json",
        supervisor_output_root=Path("/var/tmp/ds02-stage2") / ("v46-builder-test-" + tmp_path.name),
        home_path=Path("/home/jade"),
        home_min_free_bytes=536870912000,
        external_bytes=12000000000,
        home_receipt_bytes=65536,
        allow_missing_parent=True,
    )
    assert result["status"] == "READY_FOR_PARENT_V41_RELOCATED_COLD_GUARD"
    base = json.loads(parent.read_text(encoding="utf-8"))
    assert len(base["static_bindings"]) == 8
    output = tmp_path / "v46-built-parent.json"
    forwarded = V46.forward_parent(
        base_request=parent,
        output=output,
        parent_attempt_id="f2-s1-v46-real-builder-test-002",
    )
    value = json.loads(output.read_text(encoding="utf-8"))
    assert forwarded["static_binding_count"] == 16
    assert value["status"] == "READY_FOR_PARENT_GUARD"
    roles = {item["role"] for item in value["static_bindings"]}
    assert {"runtime_v2", "python_executable", "executor_v45",
            "executor_v41_compat", "executor_v43_builder", "executor_v38_compat",
            "executor_v34_compat"}.issubset(roles)
