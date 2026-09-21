from __future__ import annotations

import json
from pathlib import Path

from scripts.f2_receiver_ballistic_catch_release010_v2_negative_evidence import (
    PREFLIGHT,
    build_evidence,
)


def test_v2_preflight_is_frozen_as_zero_credit_scientific_failure() -> None:
    value = build_evidence(PREFLIGHT)
    assert value["status"] == "candidate_closed_after_cpu_native_scientific_hard_failure"
    assert value["qualification_claim"] == "none"
    assert value["T1_numerical"] is False
    assert value["matrix_credit"] == 0
    assert value["failure"]["gate"] == "outer_wall_endpoint_count_zero"
    assert value["failure"]["observed_count"] == 3840
    assert value["failure"]["same_input_retry_allowed"] is False
    assert value["denominator"]["failed_rows_dropped"] is False
    assert value["execution_controls"]["solver_invoked"] is False


def test_v2_preflight_binding_is_present_and_has_no_protected_execution() -> None:
    value = build_evidence(PREFLIGHT)
    binding = value["input_evidence"]["preflight"]
    path = Path(binding["path"])
    assert path.is_file()
    assert binding["bytes"] == path.stat().st_size
    assert len(binding["sha256"]) == 64
    assert value["execution_controls"]["registry_mutation"] == 0
    assert value["execution_controls"]["ledger_mutation"] == 0
