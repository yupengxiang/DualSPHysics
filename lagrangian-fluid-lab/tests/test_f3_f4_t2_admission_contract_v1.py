from __future__ import annotations

import hashlib
import json

from scripts.f3_f4_t2_admission_contract_v1 import (
    LAB,
    OUTPUT,
    QUALIFICATION_SCHEMA,
    REPORT,
    _require_qualification_schema,
    verify,
)


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _contract() -> dict:
    return json.loads(OUTPUT.read_text(encoding="utf-8"))


def test_synthetic_qualification_rejected_before_t2_admission_markers() -> None:
    class SchemaReadProbe(dict):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.reads = []

        def get(self, key, default=None):
            self.reads.append(key)
            if key != "schema":
                raise AssertionError(f"qualification field read before schema rejection: {key}")
            return super().get(key, default)

    for family in ("F3", "F4"):
        probe = SchemaReadProbe({
            "schema": "core.f8.synthetic_diagnostic.v1",
            "T1_numerical": True, "T2_macro": True,
            "T2_path": True, "matrix_complete": True,
        })
        try:
            _require_qualification_schema(probe, family)
        except ValueError as exc:
            assert f"{family} qualification schema mismatch" in str(exc)
        else:
            raise AssertionError(f"synthetic {family} qualification schema was accepted")
        assert probe.reads == ["schema"]
    assert QUALIFICATION_SCHEMA == "core.qualification.v1"


def test_hash_closure_covers_current_f3_f4_receipts_and_contract_code() -> None:
    value = verify(OUTPUT)
    bindings = value["hash_bindings"]
    assert len(bindings) == 10
    for item in bindings.values():
        path = LAB / item["path"]
        assert path.is_file(), item["path"]
        assert path.stat().st_size == item["bytes"]
        assert _sha(path) == item["sha256"]


def test_current_t2_state_and_fixed_failures_are_preserved() -> None:
    value = _contract()
    assert value["T2_macro"] is False
    assert value["T2_path"] is False
    assert value["qualification_credit"] == "none"
    assert value["current_qualification_state"]["F3"]["T1_numerical"] is True
    assert value["current_qualification_state"]["F4"]["T1_numerical"] is True
    assert value["historical_audit"]["f3"]["cdf_pass"] is False
    assert value["historical_audit"]["f3"]["maximum_unknown_fraction"] == 0.015625
    assert value["historical_audit"]["f4"]["all_event_windows_complete"] is False
    assert value["historical_audit"]["f4"]["all_mass_closed"] is True
    assert value["fixed_quality_gates"]["unknown_fraction_per_source_max"] == 0.01
    assert value["fixed_quality_gates"]["f3_cdf_sup_abs_difference_max"] == 0.02
    assert value["fixed_quality_gates"]["right_censor_is_unknown"] is True


def test_selects_only_deferred_f4_candidate_with_complete_source_window() -> None:
    value = _contract()
    selected = value["selected_route"]
    assert selected["family"] == "F4"
    assert selected["candidate_id"] == "f4_ess32_v2"
    assert selected["candidate_status"] == "deferred_proposal_only"
    assert selected["existing_output_stem_is_unmaterialized"] is True
    source = value["source_window_binding"]
    assert source["frames"] == 1086
    assert source["particles"] == 217485
    assert source["time_end_s"] == 4.340002980805959
    assert source["native_rows_exact"] is True
    assert source["no_stride_or_synthetic_cadence"] is True
    candidate = value["candidate_contract"]
    assert candidate["backend"] == "f4_ckdtree_visible_shepard_ess32_v2"
    assert candidate["neighbours"] == 32
    assert candidate["one_transition_counterfactual_survivors"] == 0
    assert candidate["qualification_credit"] == "none"


def test_only_root_review_can_authorize_one_cpu_sidecar() -> None:
    value = _contract()
    boundary = value["sole_future_authorization_boundary"]
    assert boundary["authorized_now"] is False
    future = boundary["if_explicitly_authorized"]
    assert future["candidate_id"] == "f4_ess32_v2"
    assert future["scope"]["seed_count"] == 512
    assert future["scope"]["frame_start"] == 0
    assert future["scope"]["frame_end"] == 1085
    assert future["scope"]["resume_boundary_frame"] == 40
    assert future["qualification_effect"].startswith("none")
    assert len(boundary["forbidden"]) >= 7


def test_no_runtime_or_core_gate_mutation_and_report_is_explicit() -> None:
    value = _contract()
    controls = value["execution_constraints"]
    assert controls["read_only_json_hash_closure"] is True
    assert controls["source_h5_reopened_by_admission"] is False
    assert controls["source_h5_rehashed_by_admission"] is False
    assert controls["old_cfd_rerun"] is False
    assert controls["solver_started"] is False
    assert controls["gpu_started"] is False
    assert controls["queue_mutation"] == 0
    assert controls["matrix_mutation"] == 0
    assert controls["registry_mutation"] == 0
    assert controls["ledger_mutation"] == 0
    assert value["current_qualification_state"]["overall_T2_credit"] == 0
    report = REPORT.read_text(encoding="utf-8")
    assert "唯一允许的下一步" in report
    assert "不重跑 CFD" in report
    assert "T2_macro=false" in report
