"""Regression tests for the proposal-only fresh source-closure audit."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest

from scripts.core_formal_planner import REQUIRED_CODE_FILES
from scripts.core_formal_source_closure_audit import (
    _snapshot_comparison,
    build_audit,
    main,
)


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "campaigns/core-v1/learning/formal-release-candidate-v4/source-closure.json"
READINESS = ROOT / "campaigns/core-v1/learning/core-formal-readiness-audit-20260921.json"
LAUNCH = ROOT / "campaigns/core-v1/learning/core-formal-launch-contract-20260921.json"
REGISTRY = ROOT / "campaigns/core-v1/registry.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _expected_mismatch(snapshot: dict, live: dict) -> list[str]:
    old = {
        row["relative_path"]: row["sha256"]
        for row in snapshot.get("files", [])
        if isinstance(row, dict) and isinstance(row.get("relative_path"), str)
        and isinstance(row.get("sha256"), str)
    }
    now = {
        row["relative_path"]: row["sha256"]
        for row in live.get("files", [])
        if isinstance(row, dict) and isinstance(row.get("relative_path"), str)
        and isinstance(row.get("sha256"), str)
    }
    return sorted(name for name in set(old) | set(now) if old.get(name) != now.get(name))


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
    assert report["formal_release"] is False
    assert report["formal_training_allowed"] is False
    assert report["root_admission_granted"] is False
    assert report["current_source_closure"]["complete"] is True
    live = report["live_source_closure"]
    historical = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert live["required_files"] == list(REQUIRED_CODE_FILES)
    assert live["required_file_count"] == len(REQUIRED_CODE_FILES)
    assert report["historical_comparison"]["mismatch_files"] == _expected_mismatch(historical, live)
    assert report["historical_comparison"]["comparison_type"] == "historical_baseline_only"
    assert report["historical_baseline"]["required_file_count"] == len(historical["required_files"])
    assert report["live_source_closure"] is report["current_source_closure"]
    assert str(len(REQUIRED_CODE_FILES)) in report["exact_next_checks"][0]["required_artifact"]
    assert "eight" not in report["exact_next_checks"][0]["required_artifact"].lower()
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
    assert payload["formal_release"] is False
    assert payload["formal_training_allowed"] is False
    assert payload["formal_job_count"] == 0
    assert payload["launch_allowed"] is False
    assert payload["root_admission_granted"] is False
    assert digest.read_text().split()[0] == _sha256(output)
    assert _sha256(REGISTRY) == before


@pytest.mark.parametrize("mutation, expected_error", [
    (lambda snapshot: snapshot.update(
        files=[snapshot["files"][0], snapshot["files"][0], snapshot["files"][1]]
    ), "file_count"),
    (lambda snapshot: snapshot.update(closure_sha256="0" * 64), "closure_sha256"),
])
def test_historical_snapshot_integrity_rejects_duplicate_rows_and_bad_closure(
        mutation, expected_error) -> None:
    rows = [
        {"relative_path": "scripts/a.py", "sha256": "a" * 64, "bytes": 1},
        {"relative_path": "scripts/b.py", "sha256": "b" * 64, "bytes": 2},
    ]
    closure_sha256 = hashlib.sha256(json.dumps([
        {"relative_path": row["relative_path"], "sha256": row["sha256"]}
        for row in rows
    ], sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    current = {
        "required_files": [row["relative_path"] for row in rows],
        "files": rows,
        "closure_sha256": closure_sha256,
    }
    snapshot = {
        "schema": "core.formal_source_closure.v1",
        "closure_version": "test",
        "hash_algorithm": "sha256",
        "required_files": list(current["required_files"]),
        "files": [dict(row) for row in rows],
        "missing_files": [],
        "complete": True,
        "closure_sha256": closure_sha256,
    }
    mutation(snapshot)

    comparison = _snapshot_comparison(current, snapshot, {"path": "snapshot.json"})

    assert comparison["matches_current"] is False
    assert comparison["fresh_snapshot_required"] is True
    assert comparison["snapshot_integrity_valid"] is False
    assert expected_error in comparison["snapshot_integrity_errors"]
