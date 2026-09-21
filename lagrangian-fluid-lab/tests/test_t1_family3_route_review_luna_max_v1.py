from __future__ import annotations

import importlib.util
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
SCRIPT = LAB / "scripts/t1_family3_route_review_luna_max_v1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("t1_family3_route_review", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bounded_route_audit_is_closed_without_credit():
    result = load_module().check()
    assert result["status"] == "route_closed_negative_no_new_hypothesis"
    assert result["qualification_credit"] == 0
    assert result["root_review_ready"] is False


def test_latest_f2_v4_failure_is_retained():
    result = load_module().check()
    assert result["f2_v4_zero_boundnor"] == 29484
    assert result["f2_v4_gate_mk18_zero_boundnor"] == 29484
    assert result["f2_v4_outer_mk17_zero_boundnor"] == 0


def test_no_protected_mutation_is_recorded():
    result = load_module().check()
    mutations = result["protected_mutations"]
    assert mutations["registry"] == 0
    assert mutations["ledger"] == 0
    assert mutations["matrix"] == 0
    assert mutations["denominator"] == 0
    assert mutations["queue"] == 0
    assert mutations["solver_invoked"] is False
    assert mutations["gpu_started"] is False


def test_checker_has_no_execution_mode():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "subprocess" not in source
    assert "subprocess.run" not in source
    assert "os.system" not in source
    assert "tools." not in source
    assert "solver" in source
    assert "--check" in source
