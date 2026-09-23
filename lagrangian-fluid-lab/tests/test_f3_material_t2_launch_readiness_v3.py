import hashlib
import json
from pathlib import Path

from scripts.f3_material_t2_launch_readiness_v3 import (
    DEFAULT_OUTPUT,
    SCHEMA,
    build_audit,
)


ROOT = Path(__file__).resolve().parents[1]


def test_row30_terminal_failure_replaces_stale_inflight_readiness() -> None:
    value = build_audit(ROOT)
    row30 = value["plan_33_logical_configurations"]["rows"][30]
    assert value["schema"] == SCHEMA
    assert value["audit_status"] == "matrix_v2_integrated_r003_terminal_failure_no_t2_credit"
    assert row30["evidence_class"] == "terminal_diagnostic_scientific_gate_failure"
    assert row30["terminal_attempt_id"] == "f3-material-30-canonical-s4-r003"
    assert row30["terminal_execution_status"] == "succeeded"
    assert row30["terminal_full_window_complete"] is True
    assert row30["per_source_unknown_gate_pass"] is False
    assert row30["row_acceptance"] is False
    assert "do not retry" in row30["next_gap"]
    assert value["next_executable_step"]["same_scope_retry_authorized"] is False


def test_matrix_denominator_and_t2_boundaries_are_preserved() -> None:
    value = build_audit(ROOT)
    assert value["plan_33_logical_configurations"]["mapped_count"] == 33
    assert value["plan_15_diagnostics"]["mapped_count"] == 15
    assert value["row30_r003_terminal_assessment"]["T2_credit"] == 0
    assert value["hard_boundaries"]["T2_macro"] is False
    assert value["hard_boundaries"]["T2_path"] is False
    assert value["hard_boundaries"]["hdf5_or_npz_opened"] is False
    assert value["scope"]["hdf5_opened"] is False
    assert value["scope"]["npz_opened"] is False


def test_v3_input_bindings_cover_r003_terminal_source_files() -> None:
    value = build_audit(ROOT)
    for name in (
        "r003_terminal_receipt",
        "readiness_adapter_v3",
        "r003_execution_receipt_json",
        "r003_trace_summary_json",
        "r003_source_preflight_json",
        "r003_checkpoint_manifest_json",
    ):
        assert name in value["input_bindings"]
    for name, binding in value["input_bindings"].items():
        path = ROOT / binding["path"]
        assert path.is_file(), name
        assert path.stat().st_size == binding["bytes"], name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == binding["sha256"], name


def test_persisted_v3_receipt_matches_live_json_only_audit() -> None:
    receipt = json.loads((ROOT / DEFAULT_OUTPUT).read_text(encoding="utf-8"))
    current = build_audit(ROOT)
    assert receipt == current
