from __future__ import annotations

import importlib.util
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
SCRIPT = LAB / "scripts/f5_wave_runup_geometry_autofill_bound_preflight_v1.py"
SPEC = importlib.util.spec_from_file_location("f5_autofill_bound_preflight", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_v4_preflight_binds_fresh_contract_and_prior_failure():
    evidence = MODULE._verify_contract()
    assert evidence["contract"]["candidate"]["case_id"] == MODULE.CASE_ID
    assert evidence["review"]["matrix_credit"] == 0


def test_v4_preflight_uses_fresh_output_stem():
    assert MODULE.OUTPUT.name == "preflight-v4"
    assert MODULE.CASE_ID.endswith("geomrepair_v4")
    assert MODULE.shared.OUTPUT == MODULE.OUTPUT
