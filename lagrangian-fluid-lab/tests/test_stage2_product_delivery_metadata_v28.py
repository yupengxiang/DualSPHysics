from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "ds_data02_stage2_product_delivery_metadata_v28.py"
SPEC = importlib.util.spec_from_file_location("stage2_product_delivery_metadata_v28", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _fixture_product(tmp_path: Path) -> tuple[Path, dict]:
    cards = {}
    inventory = []
    for i in range(1, 8):
        family = f"F{i}"
        index = {"F1": 0, "F2": 78, "F3": 96, "F4": 144, "F5": 192, "F6": 240, "F7": 288}[family]
        physical = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090" if family == "F2" else f"{family}_ANCHOR"
        cards[family] = {
            "schema": "ds02.stage2.family-card.v27", "family_id": family,
            "current_anchor": {"current_index": index, "physical_case_id": physical, "runtime_case_alias": physical, "frames": 1, "particles": 1, "actual_time_window_s": [0.0, 1.0]},
            "raw_reconstruction": {"producer_or_root_status": "F2_NATIVE_V4_TERMINAL_VERIFIED; EXECUTABLE_PORTABLE_V4_FORWARD" if family == "F2" else "ACTUAL"},
            "task_eligibility": {"physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "QI": "UNKNOWN"},
            "access_policy": {"original_trajectory_h5_opened_by_assembler": False, "materialized_label_h5_opened_by_assembler": False, "part_bi4_opened_by_assembler": False, "solver_started": False, "model_invoked": False},
        }
        inventory.append({"current_index": index, "family_id": family, "physical_case_id": physical, "anchor_card": family})
    manifest = tmp_path / "final-family-product-manifest-v27.json"
    manifest.write_text(json.dumps({"schema": "ds02.stage2.final-family-product-manifest.v27", "status": "PREPARED_ACTUAL_V25_BOUND_SEVEN_FAMILY_PRODUCT_NO_PHYSICAL_QUALIFICATION"}), encoding="utf-8")
    product = {
        "schema": "ds02.stage2.final-family-product.v27", "status": "PREPARED_ACTUAL_V25_BOUND_SEVEN_FAMILY_PRODUCT_NO_PHYSICAL_QUALIFICATION",
        "coverage": {"current_case_count": 336, "hidden_current_cases": 0, "anchor_cards": 7, "native_alias_cases": 118},
        "family_cards": cards, "case_inventory": inventory,
        "inputs": {"manifest": {"path": str(manifest), "sha256": MODULE.sha256_file(manifest)}},
        "read_policy": {"original_trajectory_h5_opened_by_this_worker": False, "materialized_label_h5_opened_by_this_worker": False, "part_bi4_opened_by_this_worker": False, "raw_solver_output_opened_by_this_worker": False, "solver_started": False, "model_invoked": False},
    }
    path = tmp_path / "final-family-product-v27.json"
    path.write_text(json.dumps(product), encoding="utf-8")
    return path, product


def test_loader_exposes_exact_f2_card_and_pending_portable_scope(tmp_path: Path):
    path, _ = _fixture_product(tmp_path)
    product = MODULE.load_product_json(path)
    assert MODULE.get_family_card(product, "F2")["current_anchor"]["current_index"] == 78
    assert MODULE.get_current_case(product, "F2", 78)["anchor_card"] == "F2"
    contract = MODULE.single_case_reproduction_contract(product, "F2")
    stages = {stage["stage"]: stage["status"] for stage in contract["stages"]}
    assert stages["native_raw_to_typed_and_label"] == "ACTUAL_NATIVE_V4_TERMINAL_VERIFIED"
    assert stages["portable_raw_to_typed_to_label_replay"] == "PENDING_CONSUMER_GUARD"
    assert stages["physical_fate_or_dynamics"] == "UNKNOWN"


def test_loader_does_not_transfer_anchor_credit_to_non_anchor_case(tmp_path: Path):
    path, product = _fixture_product(tmp_path)
    product["case_inventory"].append({"current_index": 1, "family_id": "F1", "physical_case_id": "F1_NON_ANCHOR", "anchor_card": "F1"})
    path.write_text(json.dumps(product), encoding="utf-8")
    loaded = MODULE.load_product_json(path)
    with pytest.raises(MODULE.DeliveryError, match="non-anchor case incorrectly inherits"):
        MODULE.get_current_case(loaded, "F1", 1)


def test_loader_rejects_scientific_credit_in_card(tmp_path: Path):
    path, product = _fixture_product(tmp_path)
    product["family_cards"]["F2"]["task_eligibility"]["physical_fate"] = "PASS"
    path.write_text(json.dumps(product), encoding="utf-8")
    with pytest.raises(MODULE.DeliveryError, match="grants unsupported scientific credit"):
        MODULE.load_product_json(path)
