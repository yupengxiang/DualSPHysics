from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts/ds_data02_f6_handoff_20261002_dp020_dp0125_partvtk_rigid_audit_v3.py"
SPEC = importlib.util.spec_from_file_location("ds_data02_f6_partvtk_rigid_audit_v3", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_rigid_audit_uses_consumed_partvtk_evidence_and_frozen_contract() -> None:
    assert MODULE.AUDIT_INPUT.is_file()
    assert MODULE.PARTVTK_MANIFEST.is_file()
    assert MODULE.EXPECTED_MASSBODY == 128.0
    assert MODULE.EXPECTED_CENTER == [2.4, 1.2, 1.08]
    assert MODULE.EXPECTED_INERTIA[0] > 0 and MODULE.EXPECTED_INERTIA[2] > 0


def test_rigid_audit_preserves_gpu_and_qn_pending() -> None:
    assert MODULE.OUTPUT.name == "strict_partvtk_rigid_audit_003.json"
    assert MODULE.OUTPUT.parent.name == "partvtk_002"
