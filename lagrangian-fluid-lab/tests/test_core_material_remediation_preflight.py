"""Read-only contract tests for the F3/F4 material remediation preflight artifact."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / (
    "campaigns/core-v1/material/evidence/"
    "f3-f4-t2-cpu-only-remediation-preflight-20260920.json"
)


def _load() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_preflight_is_explicitly_read_only_and_non_qualifying() -> None:
    data = _load()

    assert data["schema"] == "core.material.t2.cpu_only_remediation_preflight.v1"
    assert data["status"] == "blocked_for_qualification"
    assert data["qualification_claim"] == "none"
    assert data["qualification_credit"] == "none"
    assert data["t2_status"] == "not_established"
    assert data["t2_qualified"] is False
    assert data["T2_macro"] is False
    assert data["T2_path"] is False

    constraints = data["execution_constraints"]
    assert constraints == {
        "read_only": True,
        "new_material_computation_by_audit": False,
        "new_job_submitted": False,
        "gpu_started": False,
        "cfd_solver_started": False,
        "solver_started": False,
        "central_ledger_mutation": 0,
        "registry_mutation": 0,
        "active_h5_opened": False,
        "thresholds_changed": False,
    }


def test_preflight_evidence_hashes_and_stale_implementation_binding_is_visible() -> None:
    data = _load()

    for item in data["input_evidence"]:
        path = ROOT / item["path"]
        assert path.is_file(), item["path"]
        assert _sha256(path) == item["sha256"], item["path"]

    mismatches = []
    for relative_path, expected_hash in data["implementation_binding"]["scripts"].items():
        path = ROOT / relative_path
        assert path.is_file(), relative_path
        if _sha256(path) != expected_hash:
            mismatches.append(relative_path)

    # This blocked, immutable preflight predates the current material
    # acceptance implementation.  The mismatch remains explicit and cannot
    # be used as a current formal binding.
    assert mismatches == [
        "scripts/core_material.py",
        "scripts/core_material_acceptance.py",
    ]


def test_fixed_unknown_cadence_and_scope_gates_are_preserved() -> None:
    data = _load()
    gates = data["registered_gates"]
    assert gates["unknown_fraction_per_source_max"] == 0.01
    assert gates["f3_cdf_sup_abs_difference_max"] == 0.02
    assert gates["f3_native_dense_saved_interval_s"] == 0.002
    assert gates["f3_matched_decimation_saved_interval_s"] == 0.01
    assert gates["f4_native_dense_saved_interval_s"] == 0.002
    assert gates["f4_matched_decimation_saved_interval_s"] == 0.02
    assert gates["right_censored_is_not_acceptance"] is True
    assert gates["required_distinct_t2_families"] == 2

    f3 = data["observed_negative_state"]["f3"]
    unknown = f3["unknown_quality"]
    assert unknown["gate_pass"] is False
    assert unknown["per_source_final_unknown_fraction"]["row29"]["source0"] > 0.01
    assert unknown["per_source_final_unknown_fraction"]["row31"]["source0"] > 0.01
    assert unknown["per_source_final_unknown_fraction"]["row31"]["source1"] > 0.01
    assert f3["cdf_quality"]["gate_pass"] is False
    assert f3["native_cadence_diagnostic"]["interpolation"] is False
    assert f3["native_cadence_diagnostic"]["status"] == "diagnostic_only"
    assert f3["scope_coverage"]["formal_row_complete"] is False
    assert len(f3["scope_coverage"]["blocked_source_rows"]) == 12

    f4 = data["observed_negative_state"]["f4"]
    assert f4["unknown_quality"]["gate_pass"] is False
    assert f4["native_cadence"]["exact_dense_source_available"] is False
    assert f4["native_cadence"]["exact_matched_decimation_pair_available"] is False
    assert f4["event_window"]["complete"] is False
    assert f4["event_window"]["acceptance"] is False
    assert f4["scope_coverage"]["registered_overlay_rows"] == 33
    assert f4["scope_coverage"]["source_cfd_cells"] == 15
    assert f4["scope_coverage"]["seed_density_4096_overlays_complete"] is False


def test_remediation_and_second_family_gate_cannot_promote_diagnostics() -> None:
    data = _load()

    requirements = data["remediation_requirements"]
    assert [item["id"] for item in requirements] == ["R1", "R2", "R3", "R4"]
    assert all(item["mode"] == "cpu_only_read_only" for item in requirements)
    assert all(item["current_status"] == "blocked" for item in requirements)

    preflight = data["qualification_preflight"]
    assert preflight["overall_pass"] is False
    assert preflight["f3"]["eligible_for_t2"] is False
    assert preflight["f4"]["eligible_for_t2"] is False

    second_family = preflight["second_family_gate"]
    assert second_family["required"] is True
    assert second_family["required_distinct_t2_families"] == 2
    assert second_family["observed_independently_accepted_t2_families"] == 0
    assert second_family["pass"] is False
    assert second_family["registry_mutation"] == 0

    shortcuts = " ".join(data["prohibited_shortcuts"])
    assert "0.01" in shortcuts
    assert "GPU/CFD/solver" in shortcuts
    assert "registry" in shortcuts
