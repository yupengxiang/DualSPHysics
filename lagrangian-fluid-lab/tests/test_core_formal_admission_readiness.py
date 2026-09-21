"""Read-only admission contract for the formal Core nine-run training gate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.core_formal_planner import build_plan
from scripts.core_formal_source_closure_admission_v6 import verify_source_closure


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / (
    "campaigns/core-v1/learning/"
    "formal-training-admission-readiness-luna-max-20260920.json"
)
V6_CLOSURE = ROOT / "campaigns/core-v1/learning/formal-release-candidate-v6/source-closure.json"


def _load() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _planner_report() -> dict:
    return build_plan(
        ROOT / "campaigns/core-v1/f3-dataset-v2.json",
        evidence=ROOT / "campaigns/core-v1/evidence/f3-inherited-qualification.json",
        profile=ROOT / "campaigns/core-v1/learning/backward-resource-measurements.json",
        environment=ROOT / (
            "campaigns/core-v1/environments/cross-host-py312-torch212-cu132-v1/"
            "records/h200-import-remote.json"
        ),
        data_root=ROOT,
        code_root=ROOT,
        python_executable=ROOT / ".venv/bin/python",
        output_dir=None,
        write_specs=False,
    )


def test_admission_artifact_is_blocked_and_preserves_nine_run_denominator() -> None:
    data = _load()

    assert data["schema"] == "core.formal_training_admission_readiness.v1"
    assert data["status"] == "blocked"
    assert data["formal_admission"] is False
    assert data["formal_training"] is False
    assert data["formal_job_count"] == 0
    assert data["required_formal_job_count"] == 9
    assert data["diagnostic_job_count"] == 3
    assert data["diagnostic_runs_counted_as_formal"] is False
    assert data["qualification_claim"] == "none"


def test_formal_protocol_is_three_models_by_three_seeds_without_test_leakage() -> None:
    protocol = _load()["formal_protocol"]

    assert protocol["models"] == ["mlp", "graph_raw", "graph_residual"]
    assert protocol["seeds"] == [17, 29, 43]
    assert protocol["model_seed_product_count"] == 9
    assert protocol["updates"] == 32000
    assert protocol["checkpoint_milestones"] == [8000, 16000, 24000, 32000]
    assert protocol["validation_cases_required"] == 12
    assert protocol["validation_cases_per_family_required"] == 4
    assert protocol["test_included"] is False
    assert protocol["formal_spec_device_is_execution"] is False


def test_current_planner_reproduces_the_blocked_admission_without_writing_specs() -> None:
    data = _load()
    report = _planner_report()

    assert report["schema"] == data["planner_observation"]["planner_schema"]
    assert report["status"] == "hold"
    assert report["launch_allowed"] is False
    assert report["formal_job_count"] == 0
    assert report["required_job_count"] == 9
    assert report["submitted"] is False
    assert report["writes_ledger"] is False
    assert report["gpu_started"] is False
    assert report["audit"]["case_count"] == 32
    assert report["audit"]["production_case_count"] == 32
    assert report["audit"]["families"] == ["F3"]
    assert report["audit"]["manifest_formal_release"] is False
    assert report["audit"]["formal_eligible"] is False
    assert len(report["audit"]["hold_reasons"]) == 3
    assert data["planner_observation"]["audit"]["hard_audit_failure_case_count"] == 32


def test_evidence_and_current_source_closure_hashes_are_bound() -> None:
    data = _load()

    for item in data["input_evidence"]:
        path = ROOT / item["path"]
        assert path.is_file(), item["path"]
        assert _sha256(path) == item["sha256"], item["path"]

    current = data["source_binding"]["current_code_files"]
    assert len(current) == 8
    historical_mismatches = []
    for item in current:
        path = ROOT / item["relative_path"]
        assert path.is_file(), item["relative_path"]
        if _sha256(path) != item["sha256"]:
            historical_mismatches.append(item["relative_path"])

    assert historical_mismatches == [
        "scripts/core_learning.py", "scripts/core_contract.py", "scripts/core_models.py"
    ]

    v6 = json.loads(V6_CLOSURE.read_text(encoding="utf-8"))
    v6_result = verify_source_closure(v6, data_root=ROOT)
    assert v6_result["ok"] is True
    assert v6["namespace"] == "core-formal-release-candidate-v6"
    assert v6["formal_training_allowed"] is False
    assert v6["formal_job_count"] == 0
    for item in v6["files"]:
        path = ROOT / item["relative_path"]
        assert _sha256(path) == item["sha256"]
        assert path.stat().st_size == item["bytes"]

    assert data["source_binding"]["preprofile_source_closure_match"] is False
    assert data["source_binding"]["preprofile_mismatch_count"] == 7
    assert data["source_binding"]["pass_for_existing_preprofile_evidence"] is False


def test_formal_gates_exclude_diagnostics_and_forbid_side_effects() -> None:
    data = _load()
    gates = data["gate_evaluation"]
    assert gates["formal_manifest_release"]["pass"] is False
    assert gates["distinct_t1_families"]["observed"] == 1
    assert gates["distinct_t1_families"]["required"] == 3
    assert gates["per_case_hard_audit"]["observed_passing_cases"] == 0
    assert gates["per_case_hard_audit"]["observed_failure_cases"] == 32
    assert gates["diagnostic_exclusion"]["diagnostic_runs_counted_as_formal"] is False

    constraints = data["execution_constraints"]
    assert constraints["read_only"] is True
    assert constraints["new_optimizer_canary_started"] is False
    assert constraints["new_job_submitted"] is False
    assert constraints["gpu_started"] is False
    assert constraints["formal_runs_started"] == 0
    assert constraints["central_registry_mutation"] == 0
    assert constraints["central_ledger_mutation"] == 0
