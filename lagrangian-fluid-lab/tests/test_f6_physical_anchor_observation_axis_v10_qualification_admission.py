"""Read-only root-admission checks for the F6 v10 qualification design."""

from __future__ import annotations

import json
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
ADMISSION = LAB / (
    "campaigns/core-v1/cfd/"
    "f6-fluid-rigid-body-physical-anchor-observation-axis-v10-"
    "qualification-design-20260921/root-admission.json"
)


def load() -> dict:
    return json.loads(ADMISSION.read_text(encoding="utf-8"))


def test_admission_passes_static_review_for_all_15_cells() -> None:
    value = load()
    assert value["status"] == "admitted_for_fresh_native_preflight_only"
    assert value["static_review_pass"] is True
    assert value["cell_count"] == 15
    assert len(value["cell_ids"]) == 15
    assert len(set(value["cell_ids"])) == 15
    assert value["qualification_claim"] == "none"
    assert value["qualification_credit"] == 0
    assert value["T1"] is False
    assert value["issues"] == []


def test_admission_allows_only_fresh_native_preflight() -> None:
    value = load()
    admission = value["admission"]
    assert admission["allowed_next_step"].startswith("materialize_each_cell")
    assert admission["all_15_cells_require_independent_preflight"] is True
    for key in (
        "old_canary_input_reuse",
        "solver_authorized",
        "gpu_authorized",
        "queue_authorized",
        "registry_authorized",
        "ledger_authorized",
        "matrix_authorized",
    ):
        assert admission[key] is False


def test_admission_execution_controls_are_zero() -> None:
    controls = load()["execution_controls"]
    assert controls["definition_written"] is False
    assert controls["gencase_invoked"] is False
    assert controls["native_decode_invoked"] is False
    assert controls["solver_invoked"] is False
    assert controls["gpu_invoked"] is False
    assert controls["queue_mutation"] == 0
    assert controls["registry_mutation"] == 0
    assert controls["ledger_mutation"] == 0
    assert controls["matrix_submission"] is False
