"""Tests for the static, planning-only Core training contract."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from scripts.core_training_contract import (
    CHECKPOINT_BINDINGS,
    CENTERS,
    DEFAULT_CONTRACT,
    DEFAULT_RECEIPT,
    HIDDEN,
    MILESTONES,
    MODELS,
    SEEDS,
    UPDATES,
    build_contract,
    expected_run_ids,
    inspect_training_sources,
    verify_contract,
    verify_receipt,
)


ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_protocol_is_exactly_three_models_three_seeds_and_four_milestones() -> None:
    assert MODELS == ("mlp", "graph_raw", "graph_residual")
    assert SEEDS == (17, 29, 43)
    assert UPDATES == 32000
    assert MILESTONES == (8000, 16000, 24000, 32000)
    assert expected_run_ids() == tuple(
        f"{model}-seed{seed}" for model in MODELS for seed in SEEDS
    )


def test_live_source_observations_cover_every_requested_training_field() -> None:
    observed = inspect_training_sources(ROOT)
    assert observed["models"] == list(MODELS)
    assert observed["seeds"] == list(SEEDS)
    assert observed["updates"] == {"trainer": UPDATES, "planner": UPDATES}
    assert observed["milestones"] == {
        "trainer": list(MILESTONES), "planner": list(MILESTONES)
    }
    assert observed["centers"] == {"trainer": CENTERS, "planner": CENTERS}
    assert observed["hidden"] == {"trainer": HIDDEN, "planner": HIDDEN}
    assert observed["radius_over_h"]["config_literal_present"] is True
    assert observed["max_neighbors"] == {
        "trainer": 64, "config_literal_present": True
    }
    assert observed["optimizer"] == {
        "config_literal_present": True,
        "constructor_present": True,
    }
    assert observed["learning_rate"] == {
        "trainer": 1e-3, "planner": 1e-3
    }
    assert observed["target_normalization"]["config_literal_present"] is True
    assert observed["checkpoint_bindings"] == {
        binding: True for binding in CHECKPOINT_BINDINGS
    }
    assert observed["milestone_checkpoint_ledger"] is True


def test_committed_planning_receipt_is_hash_bound_and_zero_credit() -> None:
    report = verify_receipt(DEFAULT_RECEIPT, root=ROOT, contract_path=DEFAULT_CONTRACT)
    assert report["ok"] is True
    assert report["mismatches"] == []
    receipt = _load(DEFAULT_RECEIPT)
    contract = _load(DEFAULT_CONTRACT)
    assert receipt["schema"] == "core.training_contract.planning_receipt.v1"
    assert receipt["namespace"] == "core-v1/learning/training-contract-v1"
    assert receipt["formal_training_allowed"] is False
    assert receipt["formal_job_count"] == 0
    assert receipt["credit"] == 0
    assert receipt["qualification_claim"] == "none"
    assert contract["source_closure"]["observation_mismatches"] == []


def test_contract_and_receipt_sidecars_bind_current_bytes() -> None:
    contract_sidecar = DEFAULT_CONTRACT.with_name(DEFAULT_CONTRACT.name + ".sha256")
    receipt_sidecar = DEFAULT_RECEIPT.with_name(DEFAULT_RECEIPT.name + ".sha256")
    assert contract_sidecar.read_text(encoding="utf-8").split()[0] == _sha256(DEFAULT_CONTRACT)
    assert receipt_sidecar.read_text(encoding="utf-8").split()[0] == _sha256(DEFAULT_RECEIPT)


def test_contract_verifier_rejects_matrix_mutation() -> None:
    contract = build_contract(ROOT)
    contract["matrix"]["expected_run_ids"] = contract["matrix"]["expected_run_ids"][:-1]
    report = verify_contract(contract, root=ROOT)
    assert report["ok"] is False
    assert "matrix.expected_run_ids" in report["mismatches"]


def test_contract_verifier_rejects_checkpoint_binding_mutation() -> None:
    contract = build_contract(ROOT)
    contract["checkpoint"]["required_bindings"] = ["model_state"]
    report = verify_contract(contract, root=ROOT)
    assert report["ok"] is False
    assert "checkpoint.required_bindings" in report["mismatches"]


def test_receipt_verifier_rejects_permission_mutations() -> None:
    receipt = _load(DEFAULT_RECEIPT)
    for field, value in (
        ("formal_training_allowed", True),
        ("formal_job_count", 9),
        ("credit", 1),
        ("qualification_claim", "formal"),
    ):
        mutated = deepcopy(receipt)
        mutated[field] = value
        report = verify_receipt(mutated, root=ROOT)
        assert report["ok"] is False
        assert field in report["mismatches"]


def test_receipt_verifier_rejects_tampered_source_closure(tmp_path: Path) -> None:
    receipt = _load(DEFAULT_RECEIPT)
    receipt["source_closure"]["source_bindings"][0]["sha256"] = "0" * 64
    report = verify_receipt(receipt, root=ROOT)
    assert report["ok"] is False
    assert "source_closure.source_bindings" in report["mismatches"]


def test_receipt_verifier_rejects_tampered_bound_contract(tmp_path: Path) -> None:
    contract = _load(DEFAULT_CONTRACT)
    contract["training"]["loss_centers"] = 128
    copied_contract = tmp_path / "contract.json"
    copied_contract.write_text(json.dumps(contract), encoding="utf-8")
    receipt = _load(DEFAULT_RECEIPT)
    receipt["contract"] = {
        "path": str(copied_contract),
        "bytes": copied_contract.stat().st_size,
        "sha256": _sha256(copied_contract),
    }
    report = verify_receipt(receipt, root=ROOT)
    assert report["ok"] is False
    assert any(item.startswith("contract.training") for item in report["mismatches"])


def test_verification_is_read_only(tmp_path: Path) -> None:
    tracked = [DEFAULT_CONTRACT, DEFAULT_RECEIPT]
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in tracked}
    assert verify_receipt(DEFAULT_RECEIPT, root=ROOT, contract_path=DEFAULT_CONTRACT)["ok"]
    after = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in tracked}
    assert after == before
