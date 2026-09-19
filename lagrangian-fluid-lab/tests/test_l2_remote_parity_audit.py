from __future__ import annotations

import json
from pathlib import Path

from scripts import l2_remote_parity_audit as audit


def test_parse_status_porcelain_preserves_dirty_paths_and_branch():
    parsed = audit._parse_status_porcelain(
        "## codex/example...origin/codex/example [ahead 1]\n"
        " M tracked.py\n"
        "?? generated.txt\n"
    )
    assert parsed["branch"] == "codex/example"
    assert parsed["dirty"] is True
    assert parsed["changes"] == [" M tracked.py", "?? generated.txt"]


def test_gpu_assessment_marks_desktop_process_busy_and_protects_gpu1():
    gpus = [
        {"index": 0, "uuid": "u0", "name": "H200", "memory_used_mib": 560, "utilization_gpu_percent": 0},
        {"index": 1, "uuid": "u1", "name": "H200", "memory_used_mib": 109582, "utilization_gpu_percent": 0},
        {"index": 2, "uuid": "u2", "name": "H200", "memory_used_mib": 18, "utilization_gpu_percent": 0},
        {"index": 3, "uuid": "u3", "name": "H200", "memory_used_mib": 18, "utilization_gpu_percent": 0},
    ]
    processes = [
        {"gpu_uuid": "u0", "gpu_index": 0, "pid": 10, "process_name": "gnome-remote-desktop-daemon", "used_memory_mib": 527},
        {"gpu_uuid": "u1", "gpu_index": 1, "pid": 11, "process_name": "python", "used_memory_mib": 109558},
    ]
    result = audit.assess_gpu_availability(gpus, processes)
    assert result["availability"]["0"]["available_for_new_solver"] is False
    assert result["availability"]["2"]["available_for_new_solver"] is True
    assert result["availability"]["3"]["available_for_new_solver"] is True
    assert result["all_required_available"] is False
    assert result["protected_gpu"]["must_not_touch"] is True
    assert result["protected_gpu"]["existing_task_observed"] is True


def test_probe_is_read_only_and_uses_correct_checkout():
    command = audit.build_remote_probe_command()
    assert "/home/jade/Projects/DualSPHysics" in command
    assert "git status --porcelain=v1 --branch" in command
    assert "nvidia-smi --query-gpu" in command
    assert "nvidia-smi --query-compute-apps" in command
    assert "solver" not in command.lower()
    assert "rm " not in command
    assert "git checkout" not in command


def test_remote_snapshot_parses_probe_and_maps_process_uuid():
    probe_output = "\n".join(
        [
            "__L2R_REMOTE_PROBE_V1__",
            "__L2R_GIT_HEAD_BEGIN__",
            "abc123",
            "__L2R_GIT_HEAD_END__",
            "__L2R_GIT_BRANCH_BEGIN__",
            "codex/example",
            "__L2R_GIT_BRANCH_END__",
            "__L2R_GIT_STATUS_BEGIN__",
            "## codex/example",
            "__L2R_GIT_STATUS_END__",
            "__L2R_GPU_BEGIN__",
            "0, GPU-u0, NVIDIA H200, 100, 18, 0",
            "1, GPU-u1, NVIDIA H200, 100, 90, 0",
            "2, GPU-u2, NVIDIA H200, 100, 18, 0",
            "3, GPU-u3, NVIDIA H200, 100, 18, 0",
            "__L2R_GPU_END__",
            "__L2R_PROCESS_BEGIN__",
            "GPU-u1, 42, python, 90",
            "__L2R_PROCESS_END__",
            "__L2R_REMOTE_PROBE_END__",
        ]
    )

    def fake_runner(args, **_kwargs):
        return audit.CommandResult(tuple(args), 0, probe_output, "")

    snapshot = audit.collect_remote_snapshot(runner=fake_runner)
    assert snapshot["git"]["head"] == "abc123"
    assert snapshot["git"]["branch"] == "codex/example"
    assert snapshot["git"]["clean"] is True
    assert snapshot["git"]["processes"][0]["gpu_index"] == 1
    assert snapshot["git"]["probe_ok"] is True


def test_report_exposes_mismatch_anomalies_and_manual_sync_plan():
    local = {
        "root": "/local",
        "git": {
            "head": "local-head",
            "branch": "codex/example",
            "clean": False,
            "status": {"changes": ["?? work"]},
        },
    }
    remote = {
        "alias": "h200-deepdebris",
        "root": "/home/jade/Projects/DualSPHysics",
        "git": {
            "head": "remote-head",
            "branch": "codex/example",
            "clean": True,
            "status": {"changes": []},
            "gpus": [],
            "processes": [],
            "probe_errors": [],
        },
    }
    report = audit.build_report(local, remote, generated_at_utc="2026-09-19T00:00:00Z")
    assert report["schema"] == "l2r.remote-parity-audit.v1"
    assert report["parity"]["parity"] is False
    assert "local_worktree_dirty" in report["anomalies"]
    assert report["follow_up_sync"]["executed"] is False
    assert any("h200-deepdebris" in command for command in report["follow_up_sync"]["commands"])
    assert report["scope"]["remote_modified"] is False
    assert report["scope"]["shared_resume_state_written"] is False


def test_cli_writes_only_opt_in_standalone_output(monkeypatch, tmp_path: Path, capsys):
    report = {
        "schema": "l2r.remote-parity-audit.v1",
        "parity": {"parity": True},
        "gpu_policy": {"assessment": {"all_required_available": True}},
    }
    monkeypatch.setattr(audit, "run_audit", lambda *args, **kwargs: report)
    output = tmp_path / "remote-parity.json"
    assert audit.main(["audit", "--output", str(output)]) == 0
    assert json.loads(output.read_text()) == report
    assert json.loads(capsys.readouterr().out) == report
