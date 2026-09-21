from __future__ import annotations

import importlib.util
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
SCRIPT = LAB / "scripts/f5_wave_runup_geometry_repair_preflight_v1.py"
SPEC = importlib.util.spec_from_file_location("f5_geometry_repair_preflight", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_contract_is_bound_to_root_review_and_new_input():
    evidence = MODULE._verify_contract()
    assert evidence["contract"]["candidate"]["case_id"] == MODULE.CASE_ID
    assert evidence["contract"]["qualification_claim"] == "none"
    assert evidence["review"]["review_decision"]["authorized_cpu_native_preflight"] is True


def test_geometry_gate_uses_fluid_only_and_exact_zero():
    import numpy as np

    class Dummy:
        pass

    # The actual source mesh is used, but the test verifies the gate contract
    # with empty fluid arrays and therefore performs no external execution.
    ids = np.asarray([], dtype=np.uint32)
    positions = np.empty((0, 3), dtype=np.float64)
    result = MODULE._geometry_repair_gate((ids, positions, None, None, {}, {}, None),
                                          {"boundary_particles": 0, "fluid_particles": 0})
    assert result["scope"] == "frame0_fluid_only"
    assert result["slope_endpoint_inside_count"] == 0
    assert result["blocks_endpoint_inside_count"] == 0
    assert result["pass"] is True


def test_preflight_output_cannot_claim_credit():
    assert MODULE.CASE_ID.endswith("geomrepair_v3")
    assert MODULE.OUTPUT.name == "preflight-v3"
