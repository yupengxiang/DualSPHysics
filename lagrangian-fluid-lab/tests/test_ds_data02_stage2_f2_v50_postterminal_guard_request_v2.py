"""V52-aware post-terminal hand-off tests; all inputs are tiny JSON fixtures."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_v50_postterminal_guard_request_v2.py"
V51_SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_portable_executor_v51.py"
V52_SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_portable_executor_v52.py"
V50_FIXTURE_TEST = ROOT / "tests" / "test_ds_data02_stage2_f2_v50_postterminal_guard_request_v1.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V = _load(SCRIPT, "test_postterminal_v2")
V51 = _load(V51_SCRIPT, "test_postterminal_v2_v51")
V52 = _load(V52_SCRIPT, "test_postterminal_v2_v52")
FIX = _load(V50_FIXTURE_TEST, "test_postterminal_v2_fixture")


def _v52_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    # The shared fixture is already a tiny V51-shaped request (the V1
    # postterminal builder accepts V51).  V52 is the next forward edge.
    v51_path, parent, preflight = FIX._fixture(tmp_path)
    value = json.loads(v51_path.read_text(encoding="utf-8"))
    value["execution"]["command"][3] = "ds_data02_stage2_f2_portable_executor_v51.py"
    value["sha256"] = V51.canonical_sha(value)
    v51_path.write_text(json.dumps(value), encoding="utf-8")
    v52_path = tmp_path / "v52.json"
    V52.build_forward(v51_request=v51_path, output_request=v52_path,
                      target_root=tmp_path / "v52-target", output_root=tmp_path / "v52-products")
    # This fixture includes an optional request_binding; a real ROOT122
    # preflight omits it, while a rebinding-aware preflight must name V52.
    preflight_value = json.loads(preflight.read_text(encoding="utf-8"))
    preflight_value["request_binding"]["executor_request_sha256"] = json.loads(v52_path.read_text(encoding="utf-8"))["sha256"]
    preflight.write_text(json.dumps(preflight_value), encoding="utf-8")
    return v52_path, parent, preflight


def test_v2_handoff_uses_worker_parent_module_paths(tmp_path: Path) -> None:
    executor, parent, preflight = _v52_fixture(tmp_path)
    output = tmp_path / "postterminal-v2.json"
    result = V.build_request(executor_request=executor, parent_request=parent,
                             v50_preflight=preflight, target_root=tmp_path / "new-target",
                             output_root=tmp_path / "new-products", output=output)
    value = json.loads(output.read_text(encoding="utf-8"))
    assert result["payload_read"] is False
    assert value["schema"] == V.SCHEMA
    plan = value["forward_v52_postterminal"]["module_rebinding"]
    assert all(row["target_relative_path"].startswith("runtime/native/") for row in plan.values())
    target_root = tmp_path / "new-target"
    roles = value["runtime_closure"]["roles"]
    assert value["runtime_closure"]["materialization_path_policy"] == \
        "target_root/runtime/<target_relative_path>"
    for row in roles:
        assert row["target_path"] == str(target_root / "runtime" / row["target_relative_path"])
    copied_v14 = next(row for row in roles if row["role"] == "copied_module_v14_operator")
    assert copied_v14["target_path"] == str(
        target_root / "runtime/runtime/native/ds_data02_stage2_f2_replay_v14.py"
    )
    assert value["copied_module_import_contract"]["source_path_fallback"] == "FORBIDDEN"
    assert value["artifacts"]["fresh_v10_proof"]["status"] == "PENDING"
    assert value["qualification"] == V.V1.UNKNOWN


def test_v2_rejects_v51_without_worker_parent_rebinding(tmp_path: Path) -> None:
    v51_path, parent, preflight = FIX._fixture(tmp_path)
    with pytest.raises(V.PostterminalV2Error, match="V52 worker-parent"):
        V.build_request(executor_request=v51_path, parent_request=parent,
                        v50_preflight=preflight, target_root=tmp_path / "new-target",
                        output_root=tmp_path / "new-products", output=tmp_path / "postterminal-v2.json")
