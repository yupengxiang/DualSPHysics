"""Source-only tests for the V53 runtime-executor command path."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_portable_executor_v53.py"
V52_TEST = ROOT / "tests" / "test_ds_data02_stage2_f2_portable_executor_v52.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V = _load(SCRIPT, "test_v53_executor")
V52 = _load(V52_TEST, "test_v53_v52_fixture")


def _v52_fixture(tmp_path: Path) -> Path:
    source, _ = V52._fixture(tmp_path)
    v52 = tmp_path / "v52.json"
    V.V52.build_forward(v51_request=source, output_request=v52,
                        target_root=tmp_path / "v52-target", output_root=tmp_path / "v52-products")
    return v52


def test_v53_rewrites_command_to_actual_runtime_prefix(tmp_path: Path) -> None:
    v52 = _v52_fixture(tmp_path)
    output = tmp_path / "v53.json"
    result = V.build_forward(v52_request=v52, output_request=output,
                             target_root=tmp_path / "v53-target", output_root=tmp_path / "v53-products")
    value = json.loads(output.read_text(encoding="utf-8"))
    target = tmp_path / "v53-target"
    expected = str(target / "runtime/runtime/executor/ds_data02_stage2_f2_portable_executor_v53.py")
    assert result["payload_read"] is False
    assert value["forward_v53"]["executor_target_path"] == expected
    assert value["execution"]["command"] [3] == expected
    row = next(item for item in value["runtime_sources"] if item["role"] == "executor_v53")
    assert row["target_relative_path"] == "runtime/executor/ds_data02_stage2_f2_portable_executor_v53.py"
    assert row["target_path"] == expected
    assert value["execution"]["command_materialization_policy"] == \
        "target_root/runtime/<target_relative_path>"
    assert value["qualification"] == V.UNKNOWN


def test_v53_rejects_consumed_namespace(tmp_path: Path) -> None:
    v52 = _v52_fixture(tmp_path)
    with pytest.raises(V.PortableV53Error, match="reuse V52 namespace"):
        V.build_forward(v52_request=v52, output_request=tmp_path / "out.json",
                        target_root=tmp_path / "v52-target", output_root=tmp_path / "new-products")
