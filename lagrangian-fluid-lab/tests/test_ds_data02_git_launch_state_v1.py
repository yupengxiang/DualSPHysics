from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_git_launch_state_v1.py"
SPEC = importlib.util.spec_from_file_location("ds_data02_git_launch_state_v1_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _git(repo: Path, *args: str) -> bytes:
    env = os.environ.copy()
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return subprocess.check_output(["git", "-C", str(repo), *args], env=env)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "bounded-test")
    (repo / "tracked.txt").write_text("one\n")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "--quiet", "-m", "initial")
    return repo


def _fake_git(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "fake-git.py"
    path.write_text("#!/usr/bin/env python3\n" + textwrap.dedent(body))
    path.chmod(0o755)
    return path


def test_real_repository_reports_exact_head_status_and_diff(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "tracked.txt").write_text("one\ntwo\n")
    report = MODULE.bounded_git_launch_state(repo, timeout_seconds=2, input_paths=["tracked.txt"])
    assert report["schema"] == "ds02.stage2.git-launch-state.v1"
    assert report["status"] == "OK"
    assert len(report["commit"]) == 40
    assert report["scope"] == {
        "mode": "INPUT_SCOPE_ONLY",
        "input_paths": ["tracked.txt"],
        "full_worktree_claim": False,
    }
    expected_status = _git(repo, "status", "--porcelain=v1", "--untracked-files=all", "--", "tracked.txt")
    expected_diff = _git(repo, "diff", "--no-ext-diff", "--unified=0", "HEAD", "--", "tracked.txt")
    assert report["status_porcelain"] == expected_status.decode()
    assert report["status_porcelain_sha256"] == hashlib.sha256(expected_status).hexdigest()
    assert report["diff_sha256"] == hashlib.sha256(expected_diff).hexdigest()
    assert report["optional_locks"] is False
    assert report["environment"]["GIT_OPTIONAL_LOCKS"] == "0"


def test_timeout_is_explicit_and_does_not_claim_partial_success(tmp_path: Path) -> None:
    fake = _fake_git(tmp_path, "import time\ntime.sleep(5)\n")
    report = MODULE.bounded_git_launch_state(tmp_path, timeout_seconds=0.08, git_executable=fake)
    assert report["status"] == "TIMEOUT"
    assert report["commit"] is None
    assert report["status_porcelain"] is None
    assert report["diff_sha256"] is None
    assert report["error"]["command_index"] == 0


def test_stdout_limit_is_explicit_and_bounded(tmp_path: Path) -> None:
    fake = _fake_git(tmp_path, "import sys\nsys.stdout.write('x' * 10000)\nsys.stdout.flush()\n")
    report = MODULE.bounded_git_launch_state(tmp_path, timeout_seconds=1, max_output_bytes=1024,
                                             git_executable=fake)
    assert report["status"] == "OUTPUT_LIMIT"
    assert report["commit"] is None
    assert report["status_porcelain"] is None
    assert report["diff_sha256"] is None


def test_input_path_validation_rejects_escape_and_duplicates(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="repository-relative"):
        MODULE.bounded_git_launch_state(tmp_path, input_paths=["../outside"])
    with pytest.raises(ValueError, match="duplicates"):
        MODULE.bounded_git_launch_state(tmp_path, input_paths=["one", "one"])
