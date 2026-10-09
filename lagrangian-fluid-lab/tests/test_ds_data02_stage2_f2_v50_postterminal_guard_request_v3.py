"""Source-only tests for V53 post-terminal command materialization."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_v50_postterminal_guard_request_v3.py"
V53_SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_portable_executor_v53.py"
V2_TEST = ROOT / "tests" / "test_ds_data02_stage2_f2_v50_postterminal_guard_request_v2.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V = _load(SCRIPT, "test_postterminal_v3")
V53 = _load(V53_SCRIPT, "test_postterminal_v3_executor")
V2 = _load(V2_TEST, "test_postterminal_v3_v2_fixture")


def _v53_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    v52, parent, preflight = V2._v52_fixture(tmp_path)
    v53 = tmp_path / "v53.json"
    V53.build_forward(v52_request=v52, output_request=v53,
                      target_root=tmp_path / "v53-target", output_root=tmp_path / "v53-products")
    preflight_value = json.loads(preflight.read_text(encoding="utf-8"))
    preflight_value["request_binding"]["executor_request_sha256"] = json.loads(v53.read_text(encoding="utf-8"))["sha256"]
    preflight.write_text(json.dumps(preflight_value), encoding="utf-8")
    return v53, parent, preflight


def test_v3_postterminal_command_matches_v41_v45_materialization(tmp_path: Path) -> None:
    executor, parent, preflight = _v53_fixture(tmp_path)
    output = tmp_path / "postterminal-v3.json"
    result = V.build_request(executor_request=executor, parent_request=parent,
                             v50_preflight=preflight, target_root=tmp_path / "new-target",
                             output_root=tmp_path / "new-products", output=output)
    value = json.loads(output.read_text(encoding="utf-8"))
    target = tmp_path / "new-target"
    expected = str(target / "runtime/runtime/executor/ds_data02_stage2_f2_portable_executor_v53.py")
    assert result["payload_read"] is False
    assert value["schema"] == V.SCHEMA
    assert value["forward_v53_postterminal"]["executor_target_path"] == expected
    assert value["execution"]["command"][3] == expected
    row = next(item for item in value["runtime_closure"]["roles"] if item["role"] == "executor_v53")
    assert row["target_path"] == expected
    assert value["runtime_closure"]["schema"] == "ds02.stage2.f2-postterminal-runtime-closure.v3"


def test_v3_rejects_v52_without_command_path_marker(tmp_path: Path) -> None:
    v51, parent, preflight = V2._v52_fixture(tmp_path)
    with pytest.raises(V.PostterminalV3Error, match="V53 command-path"):
        V.build_request(executor_request=v51, parent_request=parent,
                        v50_preflight=preflight, target_root=tmp_path / "new-target",
                        output_root=tmp_path / "new-products", output=tmp_path / "out.json")
