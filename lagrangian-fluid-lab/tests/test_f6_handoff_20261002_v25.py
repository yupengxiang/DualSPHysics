from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "ds_data02_f6_handoff_20261002_v25.py"
SPEC = importlib.util.spec_from_file_location("f6_handoff_v25_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_v25_scope_keeps_medium_as_reuse_and_covers_two_mechanisms():
    assert MODULE.MECHANISMS == ("simple_free_response", "wave_no_contact")
    assert MODULE.RESOLUTIONS == ("coarse", "medium", "fine")
    assert MODULE.WINDOW_S == [0.0, 12.0]


def test_v25_dense_requests_bind_actual_xml_and_keep_gpu_pending():
    row = {
        "mechanism_id": "simple_free_response",
        "resolution_id": "coarse",
        "case_id": "F6_TEST_CASE",
        "solver": {
            "xml": "/data/F6_TEST_CASE.xml",
            "xml_sha256": "xml-hash",
            "gencase_receipt": "/data/F6_TEST_CASE/execution-receipt.json",
            "gencase_receipt_sha256": "receipt-hash",
        },
        "runparts": {
            "sha256": "runparts-hash",
            "baseline_stable_min_dt_s": 2.0e-4,
            "half_measured_baseline_min_dt_s": 1.0e-4,
            "save_interval_s": {"median": 0.05},
        },
    }
    requests = MODULE._dense_requests([row])
    assert len(requests) == 2
    for request in requests:
        assert request["source_xml"] == "/data/F6_TEST_CASE.xml"
        assert request["source_xml_sha256"] == "xml-hash"
        assert request["source_gencase_receipt"] == "/data/F6_TEST_CASE/execution-receipt.json"
        assert request["source_runparts_sha256"] == "runparts-hash"
        assert request["gpu_launch"] is False
        assert request["root_review_required"] is True
    half_save, half_dt = requests
    assert half_save["variant"] == "half_save"
    assert half_save["output_interval_s"] == MODULE.TARGET_SAVE_S
    assert half_save["internal_integrator_change"] is False
    assert half_dt["variant"] == "half_native_Dt"
    assert half_dt["fixed_dt_s"] == 1.0e-4
    assert half_dt["fixed_dt_s"] <= 0.5 * half_dt["baseline_measured_min_dt_s"]
    assert half_dt["internal_integrator_change"] is True


def test_v25_budget_is_explicitly_pending_dense_and_fixed_dt_evidence():
    assert MODULE.EVENT_BUDGET_RELATIVE == 0.02
    assert MODULE.MACRO_BUDGET_RELATIVE == 0.05
    assert MODULE.TARGET_SAVE_S == 0.025
