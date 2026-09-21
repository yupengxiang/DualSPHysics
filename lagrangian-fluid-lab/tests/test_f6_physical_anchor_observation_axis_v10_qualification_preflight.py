"""Checks for the completed v4 F6 15-cell native preflight audit."""

from __future__ import annotations

import json
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
ROOT = LAB / (
    "campaigns/core-v1/cfd/"
    "f6-fluid-rigid-body-physical-anchor-observation-axis-v10-"
    "qualification-preflight-v4-20260921"
)
AUDIT = ROOT / "qualification-preflight-audit.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_all_fifteen_native_preflights_pass_without_science_credit() -> None:
    value = load(AUDIT)
    assert value["status"] == "all_15_native_preflights_passed_no_solver_authorization"
    assert value["matrix_complete"] is True
    assert value["cell_count"] == 15
    assert value["issues"] == []
    assert value["qualification_claim"] == "none"
    assert value["qualification_credit"] == 0
    assert value["T1"] is False
    assert value["solver_authorized"] is False
    assert value["gpu_launched"] is False
    assert value["queue_mutation"] == 0
    assert value["registry_mutation"] == 0
    assert value["ledger_mutation"] == 0


def test_preflight_signature_has_thirteen_spatial_and_two_comparison_cells() -> None:
    rows = load(AUDIT)["cells"]
    assert len(rows) == 15
    assert sum(row["design_cell"] in {"spatial", "spatial_held_out"} for row in rows) == 13
    assert sum(row["design_cell"] == "internal_time" for row in rows) == 1
    assert sum(row["design_cell"] == "native_output" for row in rows) == 1
    assert all(row["pass"] is True for row in rows)
    assert {row["expected_frame_count"] for row in rows if row["design_cell"] != "native_output"} == {301}
    assert {row["expected_frame_count"] for row in rows if row["design_cell"] == "native_output"} == {601}
    assert max(abs(float(row["mass_error_relative"])) for row in rows) <= 0.05


def test_each_receipt_retains_fresh_identity_and_closed_execution_controls() -> None:
    rows = load(AUDIT)["cells"]
    for row in rows:
        receipt = load(ROOT / f"cell-{row['index']:02d}" / "native" / "preflight.json")
        assert receipt["cell_binding"]["cell_id"] == row["cell_id"]
        assert receipt["fresh_identity"]["checks"]
        assert all(receipt["fresh_identity"]["checks"].values())
        assert receipt["qualification_only"] is True
        assert receipt["qualification_claim"] == "none"
        assert receipt["qualification_credit"] == 0
        assert receipt["T1"] is False
        controls = receipt["execution_controls"]
        assert controls["solver_invoked"] is False
        assert controls["gpu_invoked"] is False
        assert controls["job_created"] is False
        assert controls["queue_mutation"] == 0
        assert controls["registry_mutation"] == 0
        assert controls["ledger_mutation"] == 0
        assert controls["matrix_submission"] is False
