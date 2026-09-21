"""Regression tests for the proposal-only fresh source-closure audit."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.core_formal_source_closure_audit import build_audit, main


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "campaigns/core-v1/learning/formal-release-candidate-v4/source-closure.json"
READINESS = ROOT / "campaigns/core-v1/learning/core-formal-readiness-audit-20260921.json"
LAUNCH = ROOT / "campaigns/core-v1/learning/core-formal-launch-contract-20260921.json"
REGISTRY = ROOT / "campaigns/core-v1/registry.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_real_audit_lists_exact_stale_files_and_keeps_proposal_unadmitted() -> None:
    report = build_audit(
        data_root=ROOT,
        historical_snapshot=SNAPSHOT,
        readiness=READINESS,
        launch_contract=LAUNCH,
    )

    assert report["status"] == "proposal_only_blocked"
    assert report["formal_job_count"] == 0
    assert report["launch_allowed"] is False
    assert report["current_source_closure"]["complete"] is True
    assert report["historical_comparison"]["mismatch_files"] == [
        "scripts/core_contract.py", "scripts/core_evaluation.py",
        "scripts/core_learning.py", "scripts/core_models.py"
    ]
    assert report["current_source_closure"]["closure_sha256"] == (
        "d692701964bfd4d0ddaa2db437b8870a2ea71e4ffbb428282398573aa89a05ba"
    )
    assert report["fresh_source_closure_proposal"]["admitted"] is False
    assert report["fresh_source_closure_proposal"]["formal_release"] is False
    assert report["checks"]["launch_contract_emits_zero_jobs"] is True
    assert report["execution_constraints"]["registry_written"] is False
    assert report["execution_constraints"]["ledger_written"] is False
    assert {item["code"] for item in report["blockers"]} == {
        "STALE_SOURCE_CLOSURE", "FORMAL_READINESS_BLOCKED", "FRESH_CLOSURE_NOT_ADMITTED"
    }


def test_cli_writes_hash_bound_audit_without_registry_mutation(tmp_path: Path) -> None:
    before = _sha256(REGISTRY)
    output = tmp_path / "source-closure-audit.json"
    digest = tmp_path / "source-closure-audit.json.sha256"
    assert main([
        "--data-root", str(ROOT),
        "--historical-snapshot", str(SNAPSHOT),
        "--readiness", str(READINESS),
        "--launch-contract", str(LAUNCH),
        "--output", str(output),
        "--sha256-output", str(digest),
    ]) == 0
    payload = json.loads(output.read_text())
    assert payload["fresh_source_closure_proposal"]["requires_root_admission"] is True
    assert digest.read_text().split()[0] == _sha256(output)
    assert _sha256(REGISTRY) == before
