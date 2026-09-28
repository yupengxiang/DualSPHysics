import json
from pathlib import Path

import pytest

from scripts import f3_graph_evaluator_artifact_readiness_contract_v1 as contract


def _report():
    return contract.build_report(contract.LAB_ROOT)


def test_static_inventory_covers_real_core_evaluate_boundary():
    report = _report()
    assert report["source_inventory"]["core_learning"]["audit"]["static_inventory_pass"] is True
    assert report["source_inventory"]["current_validator"]["audit"]["static_inventory_pass"] is True
    assert report["argv_contract"]["command_shape"] == "core_learning.py evaluate"
    assert report["argv_contract"]["model_kind_not_in_argv"] is True


def test_report_is_blocked_zero_credit_and_has_no_side_effects():
    report = _report()
    assert report["status"] == "blocked_fail_closed"
    assert report["readiness_pass"] is False
    assert report["launch_allowed"] is False
    assert report["credit"] == 0
    assert report["source_bound"] is False
    assert all(value in (False, 0) for value in report["side_effects"].values())
    assert report["input_boundary"]["checkpoint_content_opened"] is False
    assert report["input_boundary"]["trajectory_hdf5_content_opened"] is False
    assert report["input_boundary"]["evaluation_content_opened"] is False


def test_evaluator_argv_binds_real_core_learning_options_and_outputs():
    envelope = next(
        item for item in _report()["envelopes"]
        if item["model_kind"] == "graph_raw" and item["seed"] == 17
    )
    argv = envelope["evaluator"]["argv"]
    assert argv[3:5] == ["evaluate", "--manifest"]
    assert argv[argv.index("--data-root") + 1] == str(contract.LAB_ROOT)
    assert argv[argv.index("--case-id") + 1] == contract.CASE_ID
    assert argv[argv.index("--split") + 1] == contract.SPLIT
    assert argv[argv.index("--maximum-steps") + 1] == str(contract.TRANSITIONS)
    assert argv[argv.index("--chunk-size") + 1] == str(contract.CHUNK_SIZE)
    assert argv[argv.index("--device") + 1] == "cuda:0"
    assert argv[argv.index("--progress-every") + 1] == str(contract.PROGRESS_EVERY)
    assert argv[-1] == "--diagnostic"
    assert argv[argv.index("--trajectory-output") + 1] == envelope["artifacts"]["trajectory"]["path"]
    assert argv[argv.index("--progress-output") + 1] == envelope["artifacts"]["progress"]["path"]
    assert argv[argv.index("--output") + 1] == envelope["artifacts"]["evaluation"]["path"]
    assert envelope["evaluator"]["started"] is False


def test_output_schema_inventory_matches_core_learning_contract():
    report = _report()
    output = report["output_contract"]
    assert output["evaluation_json"]["schema"] == "core.evaluation.v1"
    assert set(output["evaluation_json"]["fields"]) == set(contract.EVALUATION_FIELDS)
    assert output["trajectory_hdf5"]["state_schema"] == "core.state.native_velocity.v1"
    assert set(output["trajectory_hdf5"]["attributes"]) == set(contract.HDF5_ATTRIBUTES)
    assert set(output["trajectory_hdf5"]["datasets"]) == set(contract.HDF5_DATASETS)
    assert output["trajectory_hdf5"]["frames"] == 836
    assert output["trajectory_hdf5"]["transitions"] == 835
    assert output["progress_sidecar"]["schema"] == "core.rollout.progress.v1"
    assert output["progress_sidecar"]["progress_is_not_completion_proof"] is True


def test_validator_command_is_bound_but_remains_synthetic_only():
    report = _report()
    assert report["validator_contract"]["installed_validator_mode"] == "synthetic_only"
    assert report["validator_contract"]["production_capability_admitted"] is False
    for envelope in report["envelopes"]:
        validator = envelope["validator"]
        argv = validator["argv"]
        assert "--metadata" in argv
        assert "--fixture-root" in argv
        assert "--trajectory" in argv
        assert "--report-output" in argv
        assert validator["synthetic_only"] is True
        assert validator["started"] is False
        assert validator["passed"] is False


def test_artifact_sidecars_and_natural_exit_proof_are_explicitly_unobserved():
    for envelope in _report()["envelopes"]:
        artifacts = envelope["artifacts"]
        assert set(artifacts) == {
            "evaluation", "trajectory", "progress", "validator",
            "artifact_identity", "natural_exit_proof", "terminal_receipt",
        }
        assert len({row["path"] for row in artifacts.values()}) == len(artifacts)
        assert all(row["content_opened"] is False for row in artifacts.values())
        assert envelope["artifact_identity"]["identity_receipt_present"] is False
        proof = envelope["natural_exit"]
        assert proof["proof_present"] is False
        assert proof["producer"] == "subprocess.Popen"
        assert proof["wait_method"] == "Popen.wait"
        assert proof["natural_exit"] is False
        assert proof["observed_after_exit"] is False
        assert proof["command_sha256"] == envelope["evaluator"]["argv_sha256"]


def test_fresh_namespace_is_one_shot_and_non_reusable_but_not_attested():
    report = _report()
    namespaces = [item["namespace"]["path"] for item in report["envelopes"]]
    assert len(namespaces) == len(set(namespaces)) == 6
    nonces = [item["namespace"]["nonce"] for item in report["envelopes"]]
    assert len(nonces) == len(set(nonces)) == 6
    for envelope in report["envelopes"]:
        namespace = envelope["namespace"]
        assert namespace["one_shot"] is True
        assert namespace["fresh_namespace_required"] is True
        assert namespace["freshness_attested"] is False
        assert namespace["materialized"] is False
        assert namespace["reuse_allowed"] is False
        assert namespace["atomic_create_required"] is True


def test_validate_report_round_trip_and_rejects_authority_promotion():
    report = _report()
    assert contract.validate_report(report)["report_id"] == contract.REPORT_ID
    promoted = json.loads(json.dumps(report))
    promoted["readiness_pass"] = True
    with pytest.raises(contract.ContractError, match="report drifted|promoted"):
        contract.validate_report(promoted)


def test_validate_report_rejects_artifact_content_promotion():
    report = _report()
    tampered = json.loads(json.dumps(report))
    tampered["envelopes"][0]["artifacts"]["trajectory"]["content_opened"] = True
    with pytest.raises(contract.ContractError, match="report drifted|promoted"):
        contract.validate_report(tampered)


def test_validate_report_rejects_namespace_reuse():
    report = _report()
    tampered = json.loads(json.dumps(report))
    tampered["envelopes"][1]["namespace"]["path"] = tampered["envelopes"][0]["namespace"]["path"]
    with pytest.raises(contract.ContractError, match="report drifted|reused"):
        contract.validate_report(tampered)


def test_source_audit_fails_closed_when_required_cli_or_schema_is_removed():
    source, _ = contract._read_bounded_source(
        contract.LAB_ROOT / contract.CORE_LEARNING_RELATIVE, "core_learning.py"
    )
    broken = source.replace("--diagnostic", "--diagnostic_removed", 1)
    audit = contract.audit_core_learning_source(broken)
    assert audit["static_inventory_pass"] is False
    assert audit["checks"]["required_cli_flags"] is False


def test_cli_generates_and_verifies_only_bounded_report(tmp_path):
    report_path = tmp_path / "readiness.json"
    markdown_path = tmp_path / "readiness.zh-CN.md"
    assert contract.main([
        "--root", str(contract.LAB_ROOT),
        "--report-output", str(report_path),
        "--markdown-output", str(markdown_path),
    ]) == 0
    assert report_path.is_file()
    assert markdown_path.is_file()
    assert contract.main([
        "--root", str(contract.LAB_ROOT),
        "--verify-report", str(report_path),
    ]) == 0


def test_no_runtime_execution_modules_are_imported_by_contract():
    source = Path(contract.__file__).read_text(encoding="utf-8")
    assert "import subprocess" not in source
    assert "import h5py" not in source
    assert "import torch" not in source
    assert "Popen(" not in source
