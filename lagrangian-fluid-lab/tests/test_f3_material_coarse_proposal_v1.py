"""Synthetic, read-only checks for the F3 coarse proposal contract."""

from __future__ import annotations

import json
from pathlib import Path

from scripts import f3_material_coarse_proposal_v1 as proposal


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports/F3-MATERIAL-COARSE-PROPOSAL-2026-09-28.json"


def test_current_bindings_and_fixed_fail_closed_state() -> None:
    value = proposal.build_proposal(ROOT)

    assert proposal.validate_proposal(value) == []
    assert value["status"] == "proposal_only_fail_closed"
    assert value["candidate"]["configuration_id"] == "CORE-F3-MATERIAL-COARSE-s2"
    assert value["input_bindings"]["core_material"]["sha256"] == proposal.EXPECTED_CORE_MATERIAL_SHA256
    assert value["input_bindings"]["source_h5"]["sha256"] == proposal.EXPECTED_SOURCE_SHA256
    assert value["input_bindings"]["job_spec"]["sha256"] == proposal.EXPECTED_JOB_SPEC_SHA256
    assert value["input_bindings"]["source_h5"]["hash_only"] is True
    assert value["execution_controls"]["source_hdf5_opened_as_hdf5"] is False
    assert value["execution_controls"]["material_trace_read"] is False
    assert value["execution_controls"]["material_trace_created"] is False
    assert value["fresh_attempt_namespace"]["created"] is False
    assert value["proposal_state"] == {
        "proposal_only": True,
        "diagnostic_only": True,
        "formal": False,
        "formal_eligible": False,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "T2_credit": 0,
        "T2_macro": False,
        "T2_path": False,
        "launch_admitted": False,
    }


def test_normalized_module_argv_is_exact_and_full_window() -> None:
    value = proposal.build_proposal(ROOT)
    expected = [
        str(ROOT / ".venv/bin/python"),
        "-m",
        "scripts.core_material",
        "--source",
        str(ROOT / proposal.SOURCE_H5),
        "--output",
        "{attempt_dir}/material.h5",
        "--seeds",
        "512",
        "--substeps",
        "2",
        "--neighbour-variant",
        "baseline24",
    ]
    assert value["normalized_launch"]["cwd"] == str(ROOT)
    assert value["normalized_launch"]["argv"] == expected
    assert value["normalized_launch"]["resume_argv_same_attempt"] == [*expected, "--resume"]
    assert value["normalized_launch"]["stop_after"] is None
    assert value["required_output_contract"]["native_window"] == {
        "native_frame_count": 836,
        "first_frame": 0,
        "last_committed_frame": 835,
        "partial_stop_forbidden": True,
    }


def test_checkpoint_resume_and_metric_contract_is_static_only() -> None:
    value = proposal.build_proposal(ROOT)
    output = value["required_output_contract"]

    assert output["atomic_checkpoint"]["schema"] == "core.material.checkpoint.v1"
    assert output["atomic_checkpoint"]["fields"] == list(proposal.CHECKPOINT_FIELDS)
    assert output["resume"]["same_attempt_only"] is True
    assert output["resume"]["new_attempt_after_partial_failure_forbidden"] is True
    assert "unknown_gate_pass" in output["material_json"]["top_level_fields"]
    assert "first_passage_cdf_bounds" in output["material_json"]["per_source_fields"]
    assert "residence_right_censored_unknown_mass_fraction" in output["material_json"]["per_source_fields"]
    assert value["source_manifest_contract"]["window"]["native_frame_count"] == 836
    assert value["source_manifest_contract"]["window"]["hdf5_structure_opened_by_proposal"] is False


def test_forbidden_raw_gpu_partial_and_row30_argv_are_rejected() -> None:
    bad = [
        str(ROOT / "scripts/core_material.py"),
        "--gpu",
        "--stop-after",
        "30",
        "--retry-row30",
        "f3-material-30-canonical-s4-r003",
    ]
    reasons = set(proposal.forbidden_argv_reasons(bad, ROOT))
    assert reasons == {
        "raw_script_path_forbidden",
        "module_entry_required",
        "gpu_launch_or_gpu_override_forbidden",
        "partial_or_kill_hook_forbidden",
        "row30_retry_forbidden",
    }
    assert proposal.forbidden_argv_reasons(proposal.normalized_argv(ROOT), ROOT) == []


def test_historical_raw_job_spec_is_not_silently_reused() -> None:
    value = proposal.build_proposal(ROOT)
    cli = value["cli_contract"]

    assert cli["observed_raw_script_path"] is True
    assert cli["raw_script_path_accepted"] is False
    assert cli["normalization_required"] is True
    assert "historical_job_spec_uses_forbidden_raw_script_path; use normalized module argv" in value["blocking_reasons"]
    assert value["frozen_worker_runtime_contract"]["implementation_binding"]["refresh_required_before_launch"] is True


def test_report_is_json_only_and_cannot_overwrite(tmp_path: Path) -> None:
    value = proposal.build_proposal(ROOT)
    destination = tmp_path / "proposal.json"
    written = proposal.write_report(value, destination)

    assert written == destination
    assert json.loads(destination.read_text(encoding="utf-8")) == value
    try:
        proposal.write_report(value, destination)
    except FileExistsError:
        pass
    else:
        raise AssertionError("proposal writer must not overwrite an existing report")


def test_committed_report_preserves_the_same_fail_closed_markers() -> None:
    value = json.loads(REPORT.read_text(encoding="utf-8"))
    assert proposal.validate_proposal(value) == []
    assert value["input_bindings"]["core_material"]["sha256"] == proposal.EXPECTED_CORE_MATERIAL_SHA256
    assert value["input_bindings"]["source_h5"]["sha256"] == proposal.EXPECTED_SOURCE_SHA256
    assert value["input_bindings"]["job_spec"]["sha256"] == proposal.EXPECTED_JOB_SPEC_SHA256
    assert value["proposal_state"]["qualification_credit"] == 0
    assert value["proposal_state"]["formal"] is False
