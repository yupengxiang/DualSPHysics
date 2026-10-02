from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "ds_data02_f6_handoff_20261002_v27.py"
SPEC = importlib.util.spec_from_file_location("f6_handoff_v27_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_v27_is_additive_and_explicitly_binds_rigid_contract():
    assert MODULE.DP_M == 0.025
    assert MODULE.FAMILY_ROOT.name == "commensurate_dp025_rigid003"
    assert MODULE.RIGID_CENTER == [2.4, 1.2, 1.08]
    assert MODULE.RIGID_INERTIA[0] > 0
    assert MODULE.RIGID_INERTIA[1] > 0
    assert MODULE.RIGID_INERTIA[2] > 0
    assert MODULE.FAMILY_ROOT.parent.name == "handoff_20261002"


def test_v27_definitions_contain_explicit_center_and_inertia():
    for definition in MODULE.FAMILY_ROOT.glob("cases/*/dp025/*_Def.xml"):
        text = definition.read_text(encoding="utf-8")
        assert '<center x="2.4" y="1.2" z="1.08"' in text
        assert '<inertia x="8.53333333333" y="8.53333333333" z="13.6533333333"' in text
        assert "RIGID003" in text


def test_v27_requests_are_fresh_cpu_gen_case_requests():
    manifest = json.loads((MODULE.FAMILY_ROOT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "fresh_dp025_rigid003_cpu_gencase_pending"
    assert len(manifest["cases"]) == 2
    for case in manifest["cases"]:
        request = case["request"]
        assert request["kind"] == "cpu"
        assert request["cpu_task_kind"] == "gencase"
        assert request["solver_dimension_required"] == 3
        assert request["expected"]["expected_fluid_particles"] == 327680
        assert request["expected"]["strict_continuous_fluid_mass_kg"] == 5120.000000000001
        assert request["expected"]["floating_type"] == 2
        assert any(path.endswith("ds_data02_f6_handoff_20261002_v27.py") for path in request["input_files"])
        assert any(path.endswith("ds_data02_f6_handoff_20261002_v26.py") for path in request["input_files"])
