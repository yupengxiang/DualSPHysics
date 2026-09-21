from __future__ import annotations

import json
from pathlib import Path

from scripts import f2_h2_mdbc_static_range_v5_prepare as v5


LAB = Path(__file__).resolve().parents[1]
CANDIDATE = LAB / "campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-candidate-v5.json"
PARENT = LAB / "campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-candidate-v2.json"
MATERIALIZED = LAB / "campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-v5/prepared-20260920-v5-cell11-v3"


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def test_v5_sampling_is_independent_and_all_analytic_rows_meet_frozen_mass_gates() -> None:
    card = _load(CANDIDATE)
    parent = _load(PARENT)
    cells = card["qualification_design"]["cells"]
    parent_ids = {row["case_id"] for row in parent["qualification_design"]["cells"]}

    assert card["qualification_only"] is True
    assert card["qualified"] is False
    assert card["T1_numerical"] is False
    assert card["registry_mutation"] == 0
    assert card["central_ledger_mutation"] == 0
    assert len(cells) == 15
    assert not parent_ids.intersection({row["case_id"] for row in cells})

    for cell in cells:
        sampling = v5._sampling_for_cell(cell, card)
        assert max(abs(value) for value in sampling["source_relative_errors"]) <= 0.025
        assert abs(sampling["discrete_to_continuum_mass_error"]) <= 0.03

    repaired = v5._sampling_for_cell(cells[11], card)
    assert repaired["layer_counts"] == [[43, 29, 15], [43, 29, 15], [42, 29, 16]]
    assert repaired["selected_top_lateral_counts"] == [42, 29]
    assert abs(repaired["source_relative_errors"][2] - 0.004152671755724979) < 1e-12
    assert repaired["source_relative_errors"][2] < 0.025
    assert repaired["source_relative_errors"][2] != 0.02806106870228997


def test_v5_cell11_native_preflight_is_positive_but_not_qualification_credit() -> None:
    report = _load(MATERIALIZED / "matrix-preparation.json")
    row = report["cells"][11]
    preflight = _load(Path(row["preflight"]))
    prepared = _load(Path(row["prepared"]))

    assert report["status"] == "partial_prepared"
    assert report["registered_cell_count"] == 15
    assert report["prepared_cell_count"] == 1
    assert report["unattempted_cell_count"] == 14
    assert report["failure_denominator"]["parent_v4_failed_cell_11_retained"] is True
    assert report["failure_denominator"]["parent_v4_cell_11_source_relative_errors"][2] == 0.02806106870228997
    assert row["preflight_pass"] is True
    assert row["qualification_credit"] is False
    assert preflight["preflight_pass"] is True
    assert preflight["checks"]["source_initial_mass_gate"] is True
    assert preflight["checks"]["decoded_native_mass_gate"] is True
    assert preflight["mass_gate"]["source_relative_errors"][2] < 0.025
    assert prepared["qualification_only"] is True
    assert prepared["T1_numerical"] is False
    assert prepared["solver_invoked"] is False
    assert prepared["gpu_invoked"] is False
    assert prepared["queue_mutated"] is False
    assert prepared["ledger_mutated"] is False
    assert prepared["registry_mutated"] is False
