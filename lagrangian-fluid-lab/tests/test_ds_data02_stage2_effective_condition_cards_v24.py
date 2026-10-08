from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_effective_condition_cards_v24.py"
spec = importlib.util.spec_from_file_location("effective_condition_cards_v24", SCRIPT)
assert spec and spec.loader
CARDS = importlib.util.module_from_spec(spec)
spec.loader.exec_module(CARDS)

CURRENT = ROOT / "campaigns/ds-data-02/stage2/CURRENT336.json"
QUALITY_MANIFEST = ROOT / "campaigns/ds-data-02/stage2/requests/family-label-quality-v3/f1-f7-source-role-manifest-forward-001.json"
QUALITY_REPORT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/infra/"
    "DS02_STAGE2_SEVEN_ACTUAL_FAMILY_LABEL_QUALITY_V3/"
    "seven-actual-family-label-quality-v3-root-029-001/seven-family-label-quality-v3.json"
)
QUALITY_RECEIPT = QUALITY_REPORT.parent / "execution-receipt.json"


def test_forbidden_scientific_payload_is_rejected(tmp_path: Path) -> None:
    payload = tmp_path / "trajectory.h5"
    payload.write_bytes(b"fixture")
    with pytest.raises(CARDS.CardError, match="forbidden scientific payload"):
        CARDS.require_file(payload, "fixture")


@pytest.mark.skipif(not QUALITY_REPORT.is_file(), reason="root seven-family quality report is not mounted")
def test_actual_cards_have_separate_components_and_unknown_physics(tmp_path: Path) -> None:
    output = tmp_path / "cards.json"
    result = CARDS.build_cards(CURRENT, QUALITY_MANIFEST, QUALITY_REPORT, QUALITY_RECEIPT, output)
    assert result["status"] == "PREPARED_SOURCE_BOUND_EFFECTIVE_COMPONENTS_NO_PHYSICAL_QUALIFICATION"
    assert result["anchor_count"] == 7
    assert result["component_count"] == 7
    assert result["source_role_counts"] == {"native_initial_mk": 5, "initial_spatial_region": 2}
    assert {card["family_id"] for card in result["cards"]} == {f"F{i}" for i in range(1, 8)}
    assert all(card["component_id"] == f"v24-anchor-{card['family_id']}" for card in result["cards"])
    assert all(card["task_eligibility"]["physical_fate_or_legal_flux"] == "UNKNOWN" for card in result["cards"])
    assert all(card["task_eligibility"]["dynamical_impact"] == "UNKNOWN" for card in result["cards"])
    assert all(card["condition_evidence"]["solver_receipt_binding"]["all_bound_paths_present"] for card in result["cards"])
    assert result["read_policy"]["materialized_label_h5_opened"] is False
    assert result["upstream_quality_product_read_policy"]["materialized_label_h5_opened"] is True
    assert all(card["label_product_binding"]["upstream_quality_product_materialized_label_h5_opened"] is True for card in result["cards"])
    assert result["read_policy"]["original_trajectory_h5_opened"] is False
    assert result["read_policy"]["part_bi4_opened"] is False
    assert result["read_policy"]["solver_started"] is False
    assert result["grouping_contract"]["cross_anchor_merge"] == "NOT_PROVEN_AND_DISALLOWED"
    assert all(component["merge_status"] == "NO_CROSS_ANCHOR_MERGE" for component in result["components"])
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["inputs"]["current336"]["sha256"] == result["inputs"]["current336"]["sha256"]


@pytest.mark.skipif(not QUALITY_REPORT.is_file(), reason="root seven-family quality report is not mounted")
def test_v24_request_is_small_input_only(tmp_path: Path) -> None:
    request = CARDS.make_request(
        CURRENT,
        QUALITY_MANIFEST,
        QUALITY_REPORT,
        QUALITY_RECEIPT,
        tmp_path / "request.json",
        Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics"),
        Path("/home/jade/.codex/worktrees/ds-data-02-stage2-forensics/DualSPHysics"),
    )
    assert request["launch_allowed"] is True
    assert request["cpu_threads"] == 1
    assert request["source_cost"]["materialized_label_h5_bytes_read"] == 0
    assert request["source_cost"]["original_trajectory_h5_bytes_read"] == 0
    assert request["source_cost"]["part_bi4_bytes_read"] == 0
    assert all(Path(path).suffix.lower() not in CARDS.FORBIDDEN_SUFFIXES for path in request["input_files"])
    assert request["no_cross_anchor_merge"] is True
