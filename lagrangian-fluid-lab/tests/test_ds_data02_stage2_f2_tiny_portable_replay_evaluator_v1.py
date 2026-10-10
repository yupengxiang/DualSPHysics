from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_tiny_portable_replay_evaluator_v1.py"
OBSERVER = ROOT / "scripts/ds_data02_stage2_no_model_observer_evaluator_v2.py"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


def _input(path: Path) -> None:
    value = {
        "schema": "ds02.stage2.f2-tiny-producer-input.v1",
        "query_times_s": [0.0, 1.0],
        "identity": [[0, 10], [0, 11], [0, 12]],
        "initial_mass_kg": [1.0, 2.0, 3.0],
        "positions_m": [
            [[0.0, 0.0, 0.0], [0.5, 0.0, 0.0], [1.0, 0.0, 0.0]],
            [[0.5, 0.0, 0.0], [1.0, 0.0, 0.0], [1.5, 0.0, 0.0]],
        ],
        "velocities_m_s": [
            [[1.0, 0.0, 0.0], [2.0, 0.0, 0.0], [3.0, 0.0, 0.0]],
            [[2.0, 0.0, 0.0], None, [99.0, 0.0, 0.0]],
        ],
        "valid": [[True, True, True], [True, True, False]],
    }
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-B", "-I", str(SCRIPT), *args],
                          text=True, capture_output=True, check=False)


def test_real_subprocess_chain_relocates_and_scores_with_fresh_interpreters(tmp_path: Path) -> None:
    producer_input = tmp_path / "source" / "producer-input.json"
    producer_input.parent.mkdir()
    _input(producer_input)
    old_root = tmp_path / "old-consumed-root"
    request = tmp_path / "request.json"
    fresh = tmp_path / "fresh-attempt"
    build = _run("build-request", "--producer-input", str(producer_input),
                 "--observer-script", str(OBSERVER), "--fresh-root", str(fresh),
                 "--old-root", str(old_root), "--output", str(request))
    assert build.returncode == 0, build.stderr

    report = fresh / "reports" / "chain-report.json"
    run = _run("run", "--request", str(request), "--output", str(report),
               "--parent-pid", str(__import__("os").getpid()))
    assert run.returncode == 0, run.stderr
    verify = _run("verify-report", "--report", str(report))
    assert verify.returncode == 0, verify.stderr
    value = json.loads(report.read_text(encoding="utf-8"))
    assert value["status"] == "PASS_DEVELOPMENT_TINY_PORTABLE_REPLAY_OPERATOR"
    assert value["fixture_only"] is True
    assert value["qualification"] == UNKNOWN
    assert value["original_roots_poisoned"] == []
    assert value["products"]["score"]["status"] == "PASS"
    for item in value["source_audit"].values():
        assert item["source_pre_stat"] == item["source_post_stat"]
        assert item["source_sha256"] == item["target_sha256"]
    # The copied child graph contains only target paths.  The old provenance
    # root is allowed in the request, never in the runtime report.
    assert str(old_root) not in report.read_text(encoding="utf-8")


def test_request_fails_closed_when_source_changes_before_reservation(tmp_path: Path) -> None:
    producer_input = tmp_path / "producer-input.json"
    _input(producer_input)
    request = tmp_path / "request.json"
    fresh = tmp_path / "fresh"
    build = _run("build-request", "--producer-input", str(producer_input),
                 "--fresh-root", str(fresh), "--old-root", str(tmp_path / "old"),
                 "--output", str(request))
    assert build.returncode == 0, build.stderr
    producer_input.write_text(producer_input.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    run = _run("run", "--request", str(request),
               "--output", str(fresh / "reports" / "report.json"),
               "--parent-pid", str(__import__("os").getpid()))
    assert run.returncode == 2
    assert "source changed before reservation" in run.stderr
    assert not fresh.exists()


def test_producer_rejects_non_fixture_schema_without_writing_output(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "production.v1"}), encoding="utf-8")
    output = tmp_path / "trajectory.json"
    result = _run("producer", "--input", str(bad), "--output", str(output))
    assert result.returncode == 2
    assert not output.exists()
