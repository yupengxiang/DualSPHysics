from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


FAMILY = Path(__file__).parents[1] / "campaigns/ds-data-02/families/F2"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dp005_repair_keeps_physical_population_and_aligns_all_axes():
    v1 = load("f2_commensurate_dp005_test", FAMILY / "f2_commensurate_dp005.py")
    v2 = load("f2_commensurate_dp005_v2_test", FAMILY / "f2_commensurate_dp005_v2.py")

    assert v1.EXPECTED_TOTAL == 196_608
    assert v1.CONTINUOUS_VOLUME_M3 == pytest.approx(0.024576)
    assert v1.CONTINUOUS_MASS_KG == pytest.approx(24.576)
    assert v2.RECIPE_ID.endswith("_V2")
    assert v2.GRID_ORIGIN == (-0.805, -0.8075, -0.4575)

    # The explicit cell-centre coordinates are integer dp offsets from the
    # repaired GenCase origin on every axis; v2 changes only this numerical
    # phase and therefore remains the same physical mother.
    for low, origin, count in zip(v1.FLUID_LOW, v2.GRID_ORIGIN, v1.EXPECTED_CELLS):
        first = low + v1.DP / 2.0
        index = (first - origin) / v1.DP
        assert abs(index - round(index)) < 1e-12
        last = first + (count - 1) * v1.DP
        assert abs((last - origin) / v1.DP - round((last - origin) / v1.DP)) < 1e-12


def test_dp005_audit_manifest_declares_no_new_physical_cases():
    import json

    manifest = json.loads(
        (FAMILY / "commensurate_cellcenter_dp005_v2/manifest.json").read_text()
    )
    assert manifest["new_independent_physical_case_count"] == 0
    assert manifest["registry_role"].startswith("same_COMM4_physical_mother")
    assert {case["physical_case_id"] for case in manifest["cases"]} == {
        "F2_COMM4_CENTER_V1",
        "F2_COMM4_OFFSET_V1",
    }


def test_dp005_solver_candidates_bind_completed_prefix_and_keep_event_gate_pending():
    import hashlib
    import json

    requests = sorted((FAMILY / "commensurate_cellcenter_dp005_v2/solver_requests").glob("*_request.json"))
    assert {path.stem.split("_REPAIR01")[0] for path in requests} == {
        "F2_COMM4_CENTER_V1_DP005",
        "F2_COMM4_OFFSET_V1_DP005",
    }
    for path in requests:
        request = json.loads(path.read_text())
        prefix = Path(request["gencase_prefix"])
        assert prefix.with_suffix(".xml").is_file()
        assert prefix.with_suffix(".bi4").is_file()
        assert request["status"].startswith("candidate_macro_spatial_only")
        assert request["quality_thresholds"]["timing_qualification"] is False
        assert request["qualification_claim"] == "none"
        assert request["gencase_receipt"] in request["input_sha256"]
        assert hashlib.sha256(Path(request["gencase_receipt"]).read_bytes()).hexdigest() == request["input_sha256"][request["gencase_receipt"]]
