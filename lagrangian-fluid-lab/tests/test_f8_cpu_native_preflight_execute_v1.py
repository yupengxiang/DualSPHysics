from __future__ import annotations

import ast
from pathlib import Path

from scripts import f8_cpu_native_preflight_execute_v1 as executor


ROOT = Path(__file__).resolve().parents[1]


def test_executor_is_fixed_to_the_registered_namespace_and_zero_credit_contract() -> None:
    assert executor.OUTPUT == executor.ROOT / "cpu-native-preflight-v1"
    source = (ROOT / "scripts/f8_cpu_native_preflight_execute_v1.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert "subprocess" in names
    assert "DualSPHysics5.4CPU_linux64" not in source
    assert "DualSPHysics5.4_linux64" not in source
    assert "qualification_credit\": 0" in source
    assert "same_input_retry" in source


def test_executor_rejects_any_namespace_other_than_the_registered_one(tmp_path: Path) -> None:
    try:
        executor.run_once(tmp_path / "not-registered")
    except ValueError as error:
        assert "registered F8 output namespace" in str(error)
    else:
        raise AssertionError("executor accepted an unregistered output namespace")
