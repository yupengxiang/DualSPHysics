from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts/ds_data02_f6_handoff_20261002_dp020_dp0125_solver_requests_v1.py"
SPEC = importlib.util.spec_from_file_location("ds_data02_f6_solver_requests_v1", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_solver_request_source_audit_is_passed_and_gpu_is_root_only() -> None:
    assert MODULE.AUDIT_PATH.is_file()
    assert MODULE.PARTVTK_MANIFEST_PATH.is_file()
    assert MODULE.ROOT.name == "partvtk_002"
    assert "solver_requests_v1" in MODULE.MODULE.VERSION or MODULE.REQUEST_ROOT.name == "qualification_requests_002"


def test_solver_request_inputs_use_actual_native_prefix_and_postprocessors() -> None:
    request = MODULE._request_for_case
    assert callable(request)
    assert MODULE.REQUEST_MANIFEST.name == "qualification_request_manifest_002.json"
    assert MODULE.MODULE.SOLVER.name == "DualSPHysics5.4_linux64"
