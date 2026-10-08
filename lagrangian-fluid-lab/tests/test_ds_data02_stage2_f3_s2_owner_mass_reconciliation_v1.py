from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f3_s2_owner_mass_reconciliation_v1.py"
REQUEST = (
    ROOT / "campaigns/ds-data-02/stage2/requests/"
    / "f3-s2-owner-mass-reconciliation-v1-root-forward-094-001/"
    / "f3-s2-owner-mass-reconciliation-v1-request.json"
)


def module():
    spec = importlib.util.spec_from_file_location("f3_s2_owner_mass_reconciliation_v1", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_owner_mass_classification_preserves_frozen_hardfail():
    loaded = module()
    passing = loaded.classify_grid_mass(14.58, 14.58, "PASS_DISCRETE_SAMPLE_WITHIN_ONE_PERCENT")
    failing = loaded.classify_grid_mass(15.011315712, 14.58, "HARDFAIL_DISCRETE_SAMPLE_OVER_TWO_PERCENT")
    assert passing["mass_status"].startswith("PASS_")
    assert failing["mass_status"] == "HARDFAIL_DISCRETE_SAMPLE_MASS_OVER_TWO_PERCENT"
    assert failing["relative_error_vs_continuous_owner_percent"] == pytest.approx(2.9582696296296396)
    assert failing["mass_rescale"] is False


def test_xml_projection_uses_fluid_count_times_massfluid(tmp_path: Path):
    loaded = module()
    path = tmp_path / "generated.xml"
    path.write_text(
        "<case><casedef><definition dp='0.006'/></casedef>"
        "<particles><fixed count='4'/><fluid count='3'/></particles>"
        "<constants><massfluid value='0.2'/></constants></case>",
        encoding="utf-8",
    )
    result = loaded.xml_projection(path, "fixture")
    assert result["counts"] == {"fixed": 4, "fluid": 3}
    assert result["sample_fluid_mass_kg"] == pytest.approx(0.6)


def test_manifest_is_source_bound_and_xml_json_only():
    manifest = json.loads((REQUEST.parent / "f3-s2-owner-mass-reconciliation-v1-manifest.json").read_text())
    assert manifest["read_policy"]["xml_json_only"] is True
    assert manifest["read_policy"]["vtk_opened"] is False
    assert manifest["expected"]["owner_mass_kg"] == pytest.approx(14.58)
    assert manifest["inputs"]["root081_report"]["sha256"] == module().ROOT081_SHA256
    assert manifest["inputs"]["root086_report"]["sha256"] == module().ROOT086_REPORT_SHA256


def test_request_has_no_deferred_native_payloads():
    request = json.loads(REQUEST.read_text())
    assert request["deferred_input_file_count"] == 0
    assert request["vtk_read"] is False
    assert request["bi4_read"] is False
    assert request["hdf5_read"] is False
    assert request["solver_launch"] is False
    assert request["gencase_launch"] is False
    assert request["guard_policy"]["scientific_fate_dynamics_unknown"] is True


def test_sample_mass_is_not_used_as_physical_qualification():
    loaded = module()
    result = loaded.classify_grid_mass(14.58, 14.58, "PASS_DISCRETE_SAMPLE_WITHIN_ONE_PERCENT")
    assert result["interpretation"].startswith("particle sample diagnostic")


def test_nonfinite_mass_is_rejected():
    loaded = module()
    with pytest.raises(ValueError):
        loaded.number("nan", "fixture")


def test_missing_input_is_rejected(tmp_path: Path):
    loaded = module()
    with pytest.raises(ValueError, match="not a regular file"):
        loaded.require_file(tmp_path / "missing.json", "fixture")
