import hashlib
import json
from pathlib import Path

import pytest

from scripts.f3_material_t2_launch_readiness_v2 import (
    DEFAULT_OUTPUT,
    INPUTS,
    SCHEMA,
    build_audit,
    main,
)


ROOT = Path(__file__).resolve().parents[1]


def test_v2_binds_strict_matrix_acceptance_and_retains_zero_credit() -> None:
    value = build_audit(ROOT)
    contract = value["matrix_acceptance_v2"]
    assert value["schema"] == SCHEMA
    assert contract["denominator_rows"] == 33
    assert contract["stage_row_counts"] == {
        "resolution_substep": 24,
        "cadence": 4,
        "seed_density": 5,
    }
    assert contract["row_acceptance_computed_from_typed_evidence"] is True
    assert contract["caller_boolean_only_acceptance_rejected"] is True
    assert contract["required_artifact_roles"] == [
        "comparison",
        "source_window",
        "checkpoint",
    ]
    assert contract["at_least_one_of_artifact_roles"] == ["trace", "material_output"]
    assert contract["T2_macro"] is False
    assert contract["T2_path"] is False
    assert contract["qualification_credit"] == 0
    assert value["hard_boundaries"]["qualification_credit"] == "none"


def test_row30_is_reconciled_to_r003_without_inventing_runtime_state() -> None:
    value = build_audit(ROOT)
    row30 = value["plan_33_logical_configurations"]["rows"][30]
    assert row30["historical_status_precedes_r003"] is True
    assert row30["evidence_class"] == "authorized_attempt_without_terminal_acceptance_receipt"
    assert "do not retry" in row30["next_gap"]
    attempt = value["row30_r003"]
    assert attempt["candidate"]["seeds"] == 4096
    assert attempt["candidate"]["substeps"] == 4
    assert attempt["candidate"]["full_native_interval_count"] == 835
    assert attempt["one_attempt_only"] is True
    assert attempt["cpu_cores"] == 1
    assert attempt["cpu_core_hour_cap"] == 16.0
    assert attempt["solver_forbidden"] is True
    assert attempt["gpu_forbidden"] is True
    assert attempt["runtime_process_state_observed"] is False
    assert attempt["authorization_status_is_not_runtime_status"] is True
    assert attempt["retry_or_launch_authorized_by_this_audit"] is False
    assert value["next_executable_step"]["runtime_state_observed"] is False
    assert value["next_executable_step"]["retry_or_launch_authorized"] is False


def test_v2_receipt_binds_all_inputs_and_preserves_read_only_boundaries() -> None:
    value = build_audit(ROOT)
    assert set(value["input_bindings"]) == set(INPUTS)
    for name, binding in value["input_bindings"].items():
        path = ROOT / binding["path"]
        assert path.is_file(), name
        assert path.stat().st_size == binding["bytes"], name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == binding["sha256"], name
    assert value["scope"]["hdf5_opened"] is False
    assert value["scope"]["npz_opened"] is False
    assert value["scope"]["trace_or_checkpoint_payload_opened"] is False
    assert value["scope"]["runtime_process_state_observed"] is False
    assert value["scope"]["external_binary_invocations"] == 0
    assert value["scope"]["solver_started"] is False
    assert value["scope"]["cuda_started"] is False
    assert value["scope"]["queue_submissions"] == 0
    assert value["scope"]["material_workers_started"] == 0
    assert value["hard_boundaries"]["registry_mutation"] == 0
    assert value["hard_boundaries"]["ledger_mutation"] == 0
    assert value["hard_boundaries"]["r003_attempt_started_by_this_audit"] is False
    assert str(DEFAULT_OUTPUT).endswith("f3-material-t2-launch-readiness-v2-20260923/receipt.json")


def test_persisted_v2_receipt_matches_adapter_and_input_hashes() -> None:
    receipt_path = ROOT / DEFAULT_OUTPUT
    value = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert value["schema"] == SCHEMA
    assert set(value["input_bindings"]) == set(INPUTS)
    for name, binding in value["input_bindings"].items():
        path = ROOT / binding["path"]
        assert path.is_file(), name
        assert path.stat().st_size == binding["bytes"], name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == binding["sha256"], name


def test_cli_receipt_is_immutable(tmp_path: Path) -> None:
    output = tmp_path / "receipt.json"
    args = ["--lab-root", str(ROOT), "--output", str(output)]
    assert main(args) == 0
    original = output.read_bytes()
    with pytest.raises(FileExistsError):
        main(args)
    assert output.read_bytes() == original
