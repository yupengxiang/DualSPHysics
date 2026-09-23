from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from scripts.f3_row30_r003_terminal_audit_v1 import (
    DEFAULT_OUTPUT,
    DEFAULT_ATTEMPT_DIR,
    SCHEMA,
    assess_terminal_result,
    main,
)


ROOT = Path(__file__).resolve().parents[1]


def _fixture():
    authorization = {
        "schema": "core.material.f3.row30.core_cpu_r003_authorization.v1",
        "candidate": {
            "matrix_row": 30,
            "configuration_id": "F3-material-30",
            "q": 0.5,
            "seeds": 4096,
            "substeps": 4,
            "full_native_interval_count": 835,
        },
        "resource_pool": {
            "max_attempts": 1,
            "cpu_cores": 1,
            "cpu_core_hour_cap": 16.0,
            "timeout_seconds": 57600,
            "ram_mib": 8192,
        },
        "invariants": {"solver_forbidden": True, "gpu_forbidden": True},
    }
    job_spec = {
        "schema": "core.runtime.job_spec.v1",
        "argv": ["python", "f3_native_volume_mls.py", "--seeds", "4096", "--substeps", "4", "--stop-after", "835"],
    }
    json_files = [
        {"path": name, "bytes": 10, "sha256": f"{i + 1:064x}"}
        for i, name in enumerate(("trace.summary.json", "source-preflight.json", "trace.h5.checkpoint.json"))
    ]
    result = {
        "schema": "core.execution_receipt.v1",
        "job_id": "f3-material-30-canonical-s4-r003",
        "execution_status": "succeeded",
        "returncode": 0,
        "missing_outputs": [],
        "outputs": deepcopy(json_files),
        "artifact_index": [
            *deepcopy(json_files),
            {"path": "trace.h5", "bytes": 500, "sha256": "a" * 64},
            {"path": "trace.h5.checkpoint.00000835.abc.npz", "bytes": 100, "sha256": "b" * 64},
        ],
        "usage": {
            "wall_seconds": 40000,
            "cpu_seconds_children": 39000,
            "max_child_rss_mib": 730,
            "peak_gpu_mib_sampled": 0,
        },
    }
    summary = {
        "schema": "core.material.f3.native_volume_mls.short_canary_result.v1",
        "status": "completed",
        "qualification_claim": "none",
        "seed_count": 4096,
        "binding": {"substeps": 4, "stop_after": 835},
        "source_window": {"first_frame": 0, "last_frame": 835, "frame_count_committed": 836},
        "source_rows": [
            {"source": 0, "unknown_fraction": 0.0107421875, "reliable_path_coverage": 0.9893, "residence_censored_fraction": 0.0107},
            {"source": 1, "unknown_fraction": 0.01025390625, "reliable_path_coverage": 0.9897, "residence_censored_fraction": 0.0103},
        ],
        "mass_closed": True,
        "output": {"sha256": "a" * 64},
    }
    source_preflight = {"status": "preflight_passed", "qualification_claim": "none"}
    checkpoint = {
        "schema": "core.material.f3.native_volume_mls.checkpoint.v1",
        "committed_frame": 835,
        "generation": "trace.h5.checkpoint.00000835.abc.npz",
        "checkpoint_npz": "/attempt/trace.h5.checkpoint.00000835.abc.npz",
    }
    values = {
        "authorization": authorization,
        "job_spec": job_spec,
        "result": result,
        "trace_summary": summary,
        "source_preflight": source_preflight,
        "checkpoint": checkpoint,
        "verified_json_outputs": json_files,
    }
    return values


def test_execution_success_does_not_override_both_sources_failing_unknown_gate():
    receipt = assess_terminal_result(**_fixture())
    assert receipt["schema"] == SCHEMA
    assert receipt["status"] == "completed_scientific_gate_failure"
    assert receipt["execution"]["full_native_window_complete"] is True
    assert receipt["fixed_scientific_gates"]["per_source_unknown_gate_pass"] is False
    assert [row["unknown_gate_pass"] for row in receipt["fixed_scientific_gates"]["observed_per_source_unknown_fraction"]] == [False, False]
    assert receipt["fixed_scientific_gates"]["cdf_comparison_available"] is False
    assert receipt["fixed_scientific_gates"]["row_acceptance"] is False
    assert receipt["qualification_boundary"]["T2_macro"] is False
    assert receipt["qualification_boundary"]["qualification_credit"] == 0
    assert receipt["authorization_boundary"]["single_authorized_attempt_consumed"] is True
    assert receipt["authorization_boundary"]["new_attempt_authorized_by_this_audit"] is False


def test_missing_execution_output_fails_closed():
    values = _fixture()
    values["result"]["missing_outputs"] = ["trace.summary.json"]
    with pytest.raises(ValueError, match="missing outputs"):
        assess_terminal_result(**values)


def test_nonterminal_frame_or_changed_configuration_fails_closed():
    values = _fixture()
    values["trace_summary"]["source_window"]["last_frame"] = 834
    with pytest.raises(ValueError, match="full 836-frame"):
        assess_terminal_result(**values)
    values = _fixture()
    values["job_spec"]["argv"][5] = "8"
    with pytest.raises(ValueError, match="noncanonical value"):
        assess_terminal_result(**values)


def test_resource_budget_overrun_fails_closed():
    values = _fixture()
    values["result"]["usage"]["cpu_seconds_children"] = 17 * 3600
    with pytest.raises(ValueError, match="CPU-hour cap"):
        assess_terminal_result(**values)


def test_persisted_receipt_binds_the_json_only_evidence_and_keeps_zero_credit():
    receipt_path = ROOT / DEFAULT_OUTPUT
    value = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert value["schema"] == SCHEMA
    assert value["status"] == "completed_scientific_gate_failure"
    assert value["qualification_boundary"]["T2_macro"] is False
    assert value["scope"]["hdf5_opened_or_hashed"] is False
    assert value["scope"]["npz_opened_or_hashed"] is False
    for name, binding in value["input_bindings"].items():
        path = ROOT / binding["path"]
        assert path.is_file(), name
        assert path.stat().st_size == binding["bytes"], name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == binding["sha256"], name


def test_cli_output_is_immutable(tmp_path: Path):
    output = tmp_path / "terminal-audit.json"
    args = ["--lab-root", str(ROOT), "--attempt-dir", str(DEFAULT_ATTEMPT_DIR), "--output", str(output)]
    assert main(args) == 0
    first = output.read_bytes()
    with pytest.raises(FileExistsError):
        main(args)
    assert output.read_bytes() == first
