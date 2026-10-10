from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
RUNTIME_FILES = [
    "ds_data02_runtime_v2.py",
    "ds_data02_runtime_v6.py",
    "ds_data02_runtime_v8.py",
    "ds_data02_git_launch_state_v1.py",
    "ds_data02_git_launch_state_v2.py",
    "ds_data02_runtime_v9_git_bound.py",
]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def _make_runtime_repo(tmp: Path) -> tuple[Path, Path, list[Path]]:
    repo = tmp / "runtime-repo"
    scripts = repo / "lagrangian-fluid-lab" / "scripts"
    scripts.mkdir(parents=True)
    for name in RUNTIME_FILES:
        shutil.copy2(ROOT / "scripts" / name, scripts / name)
    anchor = repo / "request-anchor.json"
    anchor.write_text('{"scope":"tiny-runtime-test"}\n')
    subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
    _git(repo, "config", "user.email", "runtime-test@example.invalid")
    _git(repo, "config", "user.name", "runtime-v9-test")
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "runtime-v9")
    return repo, scripts / "ds_data02_runtime_v9_git_bound.py", [scripts / name for name in RUNTIME_FILES] + [anchor]


def _ledger(data_root: Path) -> None:
    runtime = data_root / "runtime"
    runtime.mkdir(parents=True)
    value = {
        "schema": "ds02.resource-ledger.v1",
        "deadline_utc": "2099-01-01T00:00:00+00:00",
        "limits": {
            "gpu_seconds": 0.0,
            "cpu_core_seconds": 30.0,
            "new_storage_bytes": 1_000_000,
            "qualification_attempts": 4,
            "production_attempts": 4,
            "storage_policy": "home_free_floor",
            "home_min_free_bytes": 0,
        },
        "charges": [],
        "reservations": [],
        "attempts": [],
    }
    (runtime / "resource-ledger.json").write_text(json.dumps(value, indent=2) + "\n")


def _request(repo: Path, scripts: list[Path], data_root: Path, attempt: str,
             *, fake_git: Path | None = None) -> Path:
    request = {
        "family_id": "infra",
        "case_id": "runtime-v9-git-bound",
        "attempt_id": attempt,
        "kind": "cpu",
        "cpu_task_kind": "tests",
        "command": [str(VENV), "-c", "from pathlib import Path; Path('{attempt_root}/child.txt').write_text('ok\\n')"],
        "cwd": str(repo),
        "worktree_root": str(repo),
        "max_wall_seconds": 10,
        "cpu_threads": 1,
        "estimated_storage_bytes": 65536,
        "input_files": [str(path) for path in scripts],
        "git_snapshot_timeout_seconds": 1.0,
    }
    if fake_git is not None:
        request["git_snapshot_executable"] = str(fake_git)
        request["git_snapshot_test_only"] = True
        request["git_snapshot_timeout_seconds"] = 0.08
    path = repo / (attempt + ".request.json")
    path.write_text(json.dumps(request, indent=2) + "\n")
    return path


def _run(wrapper: Path, request: Path, data_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(VENV), "-B", "-I", str(wrapper), "run", "--request", str(request),
         "--data-root", str(data_root)],
        text=True, capture_output=True, check=False,
    )


def test_literal_venv_runtime_success_binds_scoped_git_and_accounting() -> None:
    assert VENV.is_file(), "the pinned literal venv is required for this integration test"
    with tempfile.TemporaryDirectory(prefix="ds02-v9-runtime-") as directory:
        tmp = Path(directory)
        repo, wrapper, scripts = _make_runtime_repo(tmp)
        data_root = tmp / "data-success"
        _ledger(data_root)
        request = _request(repo, scripts, data_root, "success")
        result = _run(wrapper, request, data_root)
        assert result.returncode == 0, result.stdout + result.stderr
        output = data_root / "families" / "infra" / "runtime-v9-git-bound" / "success"
        receipt_path = output / "execution-receipt.json"
        receipt = json.loads(receipt_path.read_text())
        closure = receipt["runtime_v9_git_bound"]
        assert receipt["status"] == "completed"
        assert receipt["runner_source"] == str(wrapper)
        assert receipt["runner_sha256"] == hashlib.sha256(wrapper.read_bytes()).hexdigest()
        assert closure["wrapper_sha256"] == receipt["runner_sha256"]
        assert closure["git_helper_path"].endswith("ds_data02_git_launch_state_v2.py")
        assert closure["snapshot_count"] == 2
        assert all(item["status"] == "OK" for item in closure["snapshots"])
        assert all(item["scope"]["mode"] == "INPUT_SCOPE_ONLY" for item in closure["snapshots"])
        assert all(item["scope"]["full_worktree_claim"] is False for item in closure["snapshots"])
        ledger = json.loads((data_root / "runtime/resource-ledger.json").read_text())
        assert not ledger["reservations"]
        assert len(ledger["charges"]) == 1
        assert ledger["charges"][0]["status"] == "completed"
        assert ledger["charges"][0]["cpu_core_seconds"] == receipt["cpu_core_seconds"]


def test_forced_git_timeout_is_failed_and_charged_without_clean_claim() -> None:
    assert VENV.is_file(), "the pinned literal venv is required for this integration test"
    with tempfile.TemporaryDirectory(prefix="ds02-v9-runtime-timeout-") as directory:
        tmp = Path(directory)
        repo, wrapper, scripts = _make_runtime_repo(tmp)
        fake_git = repo / "slow-git.py"
        fake_git.write_text("#!/usr/bin/env python3\nimport time\ntime.sleep(5)\n")
        fake_git.chmod(0o755)
        scripts.append(fake_git)
        _git(repo, "add", "slow-git.py")
        _git(repo, "commit", "--quiet", "-m", "slow-git")
        data_root = tmp / "data-timeout"
        _ledger(data_root)
        request = _request(repo, scripts, data_root, "timeout", fake_git=fake_git)
        result = _run(wrapper, request, data_root)
        assert result.returncode == 1, result.stdout + result.stderr
        output = data_root / "families" / "infra" / "runtime-v9-git-bound" / "timeout"
        receipt = json.loads((output / "execution-receipt.json").read_text())
        assert receipt["status"] == "failed"
        snapshots = receipt["runtime_v9_git_bound"]["snapshots"]
        assert snapshots and snapshots[0]["status"] == "TIMEOUT"
        assert snapshots[0]["commit"] is None
        assert snapshots[0]["status_porcelain"] is None
        ledger = json.loads((data_root / "runtime/resource-ledger.json").read_text())
        assert not ledger["reservations"]
        assert len(ledger["charges"]) == 1
        assert ledger["charges"][0]["status"] == "failed"
        assert ledger["charges"][0]["cpu_core_seconds"] == receipt["cpu_core_seconds"]
