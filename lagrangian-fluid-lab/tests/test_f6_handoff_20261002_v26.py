from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "ds_data02_f6_handoff_20261002_v26.py"
SPEC = importlib.util.spec_from_file_location("f6_handoff_v26_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_v26_is_a_new_two_mechanism_dp025_scope():
    assert MODULE.DP_M == 0.025
    assert MODULE.MODULE.DP_LADDER == (("dp025", 0.025),)
    assert set(MODULE.MODULE.MECHANISMS) == {"simple_free_response", "wave_no_contact"}
    assert MODULE.FAMILY_ROOT.name == "commensurate_dp025"


def test_v26_registered_physical_contract_is_unchanged():
    assert MODULE.MODULE.FLUID["low"] == [0.4, 0.4, 0.04]
    assert MODULE.MODULE.FLUID["size"] == [4.0, 1.6, 0.8]
    assert MODULE.MODULE.continuous_fluid_volume() == 5.120000000000001
    assert MODULE.MODULE.expected_fluid_particles(0.025) == 327680
    assert MODULE.MODULE.BODY["mass_kg"] == 128.0
    assert MODULE.MODULE.body_inertia()[0][0] > 0
    assert MODULE.MODULE.body_inertia()[1][1] > 0
    assert MODULE.MODULE.body_inertia()[2][2] > 0


def test_v26_generated_requests_are_cpu_only_and_source_bound():
    manifest_path = MODULE.FAMILY_ROOT / "manifest.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "fresh_dp025_cpu_gencase_pending"
    assert len(manifest["cases"]) == 2
    for case in manifest["cases"]:
        request = case["request"]
        assert request["kind"] == "cpu"
        assert request["cpu_task_kind"] == "gencase"
        assert request["solver_dimension_required"] == 3
        assert request["expected"]["expected_fluid_particles"] == 327680
        assert request["expected"]["strict_continuous_fluid_mass_kg"] == 5120.000000000001
        assert request["expected"]["floating_type"] == 2
        assert request["expected"]["fluid_type"] == 3
        assert request["command"][0].endswith("GenCase_linux64")
        assert request["attempt_id"].endswith("_GENCASE_001")
        assert any(path.endswith("ds_data02_f6_handoff_20261002_v26.py") for path in request["input_files"])
        if case["mechanism_id"] == "wave_no_contact":
            assert request["expected"]["minimum_moving_paddle_particles"] == 1
        else:
            assert request["expected"]["minimum_moving_paddle_particles"] == 0
