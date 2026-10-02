from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ds_data02_f6_handoff_20261002_v22.py"
SPEC = importlib.util.spec_from_file_location("ds_data02_f6_handoff_20261002_v22", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
F6 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(F6)


def test_partvtkout_v2_binds_all_rows_to_initial_fluid_and_runparts() -> None:
    audit = F6.read_json(F6.POST_ROOT / "partvtkout_reconciliation_002.json")
    assert audit["status"] == "review_only"
    assert len(audit["cases"]) == 6
    for case in audit["cases"]:
        checks = case["native_reconciliation_checks"]
        assert checks["receipt_completed_code0"] is True
        assert checks["partout_row_count_equals_runparts_npout"] is True
        assert checks["all_partout_rows_are_initial_fluid_cohort"] is True
        assert checks["native_reason_unknown_count"] == 0
        assert case["unknown_physical_destination_preserved"] is True
        assert case["q_n_status"] == "pending_native_exclusion_reconciliation"


def test_first_missing_fluid_rows_retain_positions_and_unknown_destination() -> None:
    audit = F6.read_json(F6.POST_ROOT / "partvtkout_reconciliation_002.json")
    by_case = {row["case_id"]: row for row in audit["cases"]}
    simple_coarse = by_case["F6_HANDOFF_20261002_SIMPLE_FREE_RESPONSE_RIGID003_DOMAIN_XY_REPAIR_02_COARSE"]
    first = simple_coarse["initial_fluid_cohort"]["first_missing_rows"][0]
    assert first["particle_id"] == 8020
    assert first["native_reason"] == "position"
    assert first["outside_generated_xml_numeric_bbox_axes"] == ["z"]
    assert first["destination_after_exclusion"] == "unknown"
    wave_medium = by_case["F6_HANDOFF_20261002_WAVE_NO_CONTACT_RIGID003_DOMAIN_X_REPAIR_01_MEDIUM"]
    assert wave_medium["initial_fluid_cohort"]["first_missing_rows"] == []
    assert wave_medium["native_reconciliation_checks"]["no_rows_and_zero_runparts_is_explicit"] is True

