"""Tests for the CPU-only full-field/halo oracle interface witness."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from scripts.core_fullfield_halo_oracle import main, run_diagnostic, verify_receipt


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "campaigns/core-v1/learning/core-fullfield-halo-oracle-diagnostic-20260921.json"
REGISTRY = ROOT / "campaigns/core-v1/registry.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_real_receipt_is_hash_bound_and_nonformal() -> None:
    payload = json.loads(RECEIPT.read_text(encoding="utf-8"))
    result = verify_receipt(payload, data_root=ROOT)

    # This immutable diagnostic receipt predates the current public source
    # closure.  Rehashing must therefore report it as stale rather than
    # silently blessing old implementation bytes; a fresh run_diagnostic()
    # below still proves the live interface.
    assert result["ok"] is False
    assert result["mismatch_paths"] == [
        "scripts/core_fullfield_halo_oracle.py",
        "scripts/core_learning.py", "scripts/core_models.py",
        "scripts/core_contract.py",
    ]
    assert payload["status"] == "diagnostic_passed"
    assert payload["proposal_only"] is True
    assert payload["diagnostic_only"] is True
    assert payload["training_excluded"] is True
    assert payload["qualification_excluded"] is True
    assert payload["formal_release"] is False
    assert payload["formal_training"] is False
    assert payload["formal_job_count"] == 0
    assert payload["formal_runs_counted"] == 0
    assert payload["execution_constraints"]["registry_written"] is False
    assert payload["execution_constraints"]["ledger_written"] is False

    assert payload["checks"] == {
        "all_centers_covered_once": True,
        "full_particle_axis_preserved": True,
        "full_vs_chunk_commit_equivalent": True,
        "full_vs_chunk_prediction_equivalent": True,
        "future_state_rejected": True,
        "halo_indices_in_full_field": True,
        "oracle_dx_dv_independent": True,
        "oracle_predict_commit_position_exact": True,
        "oracle_predict_commit_velocity_exact": True,
        "updater_oracle_position_exact": True,
        "updater_oracle_velocity_exact": True,
    }
    assert payload["dual_increment_oracle"]["independent_velocity_semantics"] is True
    assert payload["dual_increment_oracle"]["future_state_passed_to_predictor"] is False
    assert payload["causal_rejection"]["rejected"] is True
    assert payload["full_field_halo"]["full_vs_chunk_max_abs_error"] < 1e-7


def test_cpu_witness_rechecks_interfaces_and_preserves_full_axis() -> None:
    payload = run_diagnostic(data_root=ROOT)
    assert all(payload["checks"].values())
    assert payload["protocol"]["device"] == "cpu"
    assert payload["protocol"]["optimizer_started"] is False
    assert payload["protocol"]["gpu_started"] is False
    assert payload["full_field_halo"]["neighbor_diagnostics"]["field_particle_count"] == 8
    assert len(payload["full_field_halo"]["chunks"]) == 4
    assert all(row["two_hop_count"] == 8 for row in payload["full_field_halo"]["chunks"])
    assert payload["dual_increment_oracle"]["predict_commit_position_max_abs_error"] == 0.0
    assert payload["dual_increment_oracle"]["predict_commit_velocity_max_abs_error"] == 0.0


def test_cli_and_verifier_are_read_only_and_detect_binding_tamper(tmp_path: Path) -> None:
    before = _sha256(REGISTRY)
    output = tmp_path / "diagnostic.json"
    digest = tmp_path / "diagnostic.json.sha256"
    assert main([
        "--data-root", str(ROOT),
        "--output", str(output),
        "--sha256-output", str(digest),
    ]) == 0
    generated = json.loads(output.read_text(encoding="utf-8"))
    assert main([
        "--verify", "--data-root", str(ROOT), "--input", str(output),
    ]) == 0
    assert digest.read_text(encoding="utf-8").split()[0] == _sha256(output)
    assert _sha256(REGISTRY) == before

    tampered = copy.deepcopy(generated)
    tampered["interface_audit"]["source_bindings"][0]["sha256"] = "0" * 64
    assert verify_receipt(tampered, data_root=ROOT)["ok"] is False
    assert _sha256(REGISTRY) == before
