from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / (
    "campaigns/core-v1/material/evidence/"
    "f3-row24-native002-vs-matched010-negative-acceptance-receipt-20260922.json"
)
COMPARISON = ROOT / (
    "campaigns/core-v1/material/evidence/"
    "f3-row24-native002-vs-matched010-comparison-20260922.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_row24_negative_receipt_preserves_fixed_gate_failure() -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    comparison = json.loads(COMPARISON.read_text(encoding="utf-8"))

    assert receipt["schema"] == "core.material.f3.t2.row24.temporal_acceptance_receipt.v1"
    assert receipt["status"] == "scientific_gate_failed_zero_credit"
    assert receipt["qualification_claim"] == "none"
    assert receipt["qualification_credit"] == 0
    assert receipt["T2_macro"] is False
    assert receipt["registered_gates"]["cdf_sup_abs_difference_max"] == 0.02
    assert receipt["gate_results"]["source_window_complete"] is True
    assert receipt["gate_results"]["unknown_gate_pass"] is True
    assert receipt["gate_results"]["all_cdf_events_pass"] is False
    assert receipt["denominator_effect"]["t2_denominator_increment"] == 0

    for source_id, row in receipt["observed"]["by_source"].items():
        observed = comparison["source_comparison"][source_id]["difference"]
        assert row["first_passage_cdf_sup_abs_difference"] == observed[
            "first_passage_cdf_sup_abs_difference_bound"
        ]
        assert row["return_cdf_sup_abs_difference"] == observed["return_cdf_sup_abs_difference_bound"]
        assert row["residence_cdf_sup_abs_difference"] == observed[
            "residence_cdf_sup_abs_difference_bound"
        ]


def test_row24_receipt_binds_comparison_artifact() -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    binding = receipt["artifacts"]["comparison"]
    assert (ROOT / binding["path"]).is_file()
    assert _sha256(ROOT / binding["path"]) == binding["sha256"]
