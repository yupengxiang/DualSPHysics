from __future__ import annotations

import json
from pathlib import Path

from scripts import f4_reconstruction_gate_interval_canary_v1 as canary
from scripts import f4_tallwall120_material as tw


ROOT = Path(__file__).resolve().parents[1]


def test_registered_native_source_brackets_frame_40_to_41() -> None:
    source, audit = canary.resolve_source(ROOT)
    interval = canary.validate_source_interval(source)
    assert audit["schema"] == "core.material.f4.tallwall120.cadence_source_audit.v1"
    assert audit["pair"]["cell14_role"] == "native_dense_reference_source"
    assert interval["from_frame"] == 40
    assert interval["to_frame"] == 41
    assert interval["from_time_s"] == canary.EXPECTED_FIRST_FAILURE_INTERVAL_S[0]
    assert interval["to_time_s"] == canary.EXPECTED_FIRST_FAILURE_INTERVAL_S[1]


def test_canary_contract_keeps_fixed_seed_and_gate_semantics() -> None:
    assert canary.SEEDS == 512
    assert canary.SUBSTEPS == 2
    assert canary.STOP_AFTER_FRAME == 41
    assert canary.FIRST_FAILURE_FROM_FRAME == 40
    assert tw.GATE["maximum_reconstruction_error_mps"] == 0.05 * (9.81 * 0.09) ** 0.5
    assert tw.GATE["minimum_effective_sample_size"] == 4.0
    assert tw.GATE["minimum_geometry_rank"] == 3
    assert tw.GATE["minimum_anisotropy"] == 0.005
    assert tw.MAXIMUM_SUPPORT_DISTANCE_M == 0.03


def test_source_audit_hash_is_the_registered_native004_binding() -> None:
    source_audit = json.loads(
        (ROOT / canary.SOURCE_AUDIT).read_text(encoding="utf-8")
    )
    assert source_audit["pair"]["cell14_h5"]["sha256"] == canary.EXPECTED_SOURCE_SHA256
    assert source_audit["pair"]["same_terminal_lineage"] is True
    assert source_audit["pair"]["derived_view_role"] == "exact_every_fifth_saved_row; no interpolation"


def test_interval_canary_is_diagnostic_only() -> None:
    assert canary.SCHEMA == "core.material.f4.reconstruction_gate_interval_canary.v1"
    assert canary.DP_M == 0.0075
    assert canary.Q == 0.5
    # The wrapper has no code path that can turn the bounded replay into a claim;
    # the schema itself identifies this artifact as a canary diagnostic.
    assert canary.SCHEMA.endswith("_canary.v1")
