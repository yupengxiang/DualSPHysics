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

