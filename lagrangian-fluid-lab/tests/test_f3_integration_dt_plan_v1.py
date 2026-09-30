"""Checks for the measured-baseline fixed-dt F3 sensitivity plan."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
PLAN = LAB / "campaigns/ds-data-02/families/F3/observation_plan.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def test_integration_plan_uses_measured_fixed_dt_and_same_save_cadence() -> None:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    study = plan["integration_step_study"]
    assert "registered_dtmin_half" not in json.dumps(study)
    assert "fixed_dt_half_measured_min" in json.dumps(study)
    assert any("summed Steps" in rule for rule in study["rules"])
    assert any("DtFixed" in rule for rule in study["rules"])

    for case in study["cases"]:
        assert case["output_interval_s"] == 0.0025
        baseline = case["baseline_source"]
        run_parts = Path(baseline["run_parts"])
        assert run_parts.is_file()
        assert _sha256(run_parts) == baseline["run_parts_sha256"]
        if case["integration_variant"] == "fixed_dt_half_measured_min":
            fixed = case["fixed_dt_parameter"]
            assert fixed["key"] == "DtFixed"
            assert fixed["value_s"] <= 0.5 * baseline["native_min_dt_s"]
            assert case["same_geometry_control_save_contract"] is True
        else:
            assert case["fixed_dt_parameter"] is None

