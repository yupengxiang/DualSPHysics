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
    "ds_data02_runtime_v2.py", "ds_data02_runtime_v6.py", "ds_data02_runtime_v8.py",
    "ds_data02_git_launch_state_v1.py", "ds_data02_git_launch_state_v2.py",
    "ds_data02_git_launch_state_v3.py", "ds_data02_runtime_v9_git_bound.py",
    "ds_data02_runtime_v10_git_bound.py",
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
    anchor.write_text('{"scope":"tiny-runtime-v10-test"}\n')
    subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
    _git(repo, "config", "user.email", "runtime-test@example.invalid")
    _git(repo, "config", "user.name", "runtime-v10-test")
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "runtime-v10")
    return repo, scripts / "ds_data02_runtime_v10_git_bound.py", [scripts / name for name in RUNTIME_FILES] + [anchor]


def _ledger(data_root: Path) -> None:
    runtime = data_root / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "resource-ledger.json").write_text(json.dumps({
        "schema": "ds02.resource-ledger.v1",
        "deadline_utc": "2099-01-01T00:00:00+00:00",
        "limits": {"gpu_seconds": 0.0, "cpu_core_seconds": 30.0,
                   "new_storage_bytes": 1_000_000, "qualification_attempts": 4,
                   "production_attempts": 4, "storage_policy": "home_free_floor",
                   "home_min_free_bytes": 0},
        "charges": [], "reservations": [], "attempts": [],
    }, indent=2) + "\n")


def _request(repo: Path, scripts: list[Path], data_root: Path, attempt: str,
             *, mutate: Path | None = None) -> Path:
    command = "from pathlib import Path; Path('{attempt_root}/child.txt').write_text('ok\\n')"
    if mutate is not None:
        command = (f"from pathlib import Path; Path({str(mutate)!r}).write_text('changed\\n'); "
                   "Path('{attempt_root}/child.txt').write_text('ok\\n')")
    request = {
        "family_id": "infra", "case_id": "runtime-v10-git-bound", "attempt_id": attempt,
        "kind": "cpu", "cpu_task_kind": "tests",
        "command": [str(VENV), "-c", command],
        "cwd": str(repo), "worktree_root": str(repo), "max_wall_seconds": 10,
        "cpu_threads": 1, "estimated_storage_bytes": 65536,
        "input_files": [str(path) for path in scripts], "git_snapshot_timeout_seconds": 1.0,
    }
    path = repo / (attempt + ".request.json")
    path.write_text(json.dumps(request, indent=2) + "\n")
    return path


def _run(wrapper: Path, request: Path, data_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(VENV), "-B", "-I", str(wrapper), "run", "--request", str(request),
                           "--data-root", str(data_root)], text=True, capture_output=True,
                          check=False)


def test_v10_binds_v1_v2_v3_and_closes_real_runtime() -> None:
    assert VENV.is_file()
    with tempfile.TemporaryDirectory(prefix="ds02-v10-runtime-") as directory:
        tmp = Path(directory)
        repo, wrapper, scripts = _make_runtime_repo(tmp)
        data_root = tmp / "data"
        _ledger(data_root)
        request = _request(repo, scripts, data_root, "success")
        result = _run(wrapper, request, data_root)
        assert result.returncode == 0, result.stdout + result.stderr
        receipt_path = data_root / "families" / "infra" / "runtime-v10-git-bound" / "success" / "execution-receipt.json"
        receipt = json.loads(receipt_path.read_text())
        assert receipt["status"] == "completed"
        closure = receipt["runtime_v10_git_bound"]
        assert {item["role"] for item in closure["git_helpers"]} == {
            "git_snapshot_v1", "git_snapshot_v2", "git_snapshot_v3"
        }
        assert all(Path(item["path"]).is_file() for item in closure["git_helpers"])
        assert closure["cleanup_contract"]["owned_group_cleanup_on_signal"] is True
        assert receipt["runtime_v9_git_bound"]["snapshot_count"] == 2
        assert all(s["status"] == "OK" for s in receipt["runtime_v9_git_bound"]["snapshots"])
        assert receipt["runner_sha256"] == hashlib.sha256(wrapper.read_bytes()).hexdigest()
        ledger = json.loads((data_root / "runtime/resource-ledger.json").read_text())
        assert not ledger["reservations"]
        assert len(ledger["charges"]) == 1


def test_v10_requires_v1_helper_in_static_closure() -> None:
    # The closure check is intentionally source-level and does not permit a
    # V2/V3-only request to masquerade as a complete runtime.
    wrapper = ROOT / "scripts" / "ds_data02_runtime_v10_git_bound.py"
    text = wrapper.read_text()
    assert "git_snapshot_v1" in text
    assert "V1_HELPER_PATH" in text


def test_v10_missing_v1_binding_is_rejected_before_child() -> None:
    assert VENV.is_file()
    with tempfile.TemporaryDirectory(prefix="ds02-v10-missing-v1-") as directory:
        tmp = Path(directory)
        repo, wrapper, scripts = _make_runtime_repo(tmp)
        scripts = [path for path in scripts if path.name != "ds_data02_git_launch_state_v1.py"]
        data_root = tmp / "data"
        _ledger(data_root)
        request = _request(repo, scripts, data_root, "missing-v1")
        result = _run(wrapper, request, data_root)
        assert result.returncode != 0
        assert "git_snapshot_v1" in (result.stdout + result.stderr)
        ledger = json.loads((data_root / "runtime/resource-ledger.json").read_text())
        assert ledger["reservations"] == []
        assert len(ledger["charges"]) == 1
        assert ledger["charges"][0]["status"] == "failed"
        receipt = json.loads((data_root / "families" / "infra" / "runtime-v10-git-bound" /
                              "missing-v1" / "execution-receipt.json").read_text())
        assert receipt["status"] == "failed"


def test_v10_real_child_mutation_fails_source_prepost_and_closes_charge() -> None:
    assert VENV.is_file()
    with tempfile.TemporaryDirectory(prefix="ds02-v10-prepost-") as directory:
        tmp = Path(directory)
        repo, wrapper, scripts = _make_runtime_repo(tmp)
        data_root = tmp / "data"
        _ledger(data_root)
        anchor = repo / "request-anchor.json"
        request = _request(repo, scripts, data_root, "prepost", mutate=anchor)
        result = _run(wrapper, request, data_root)
        assert result.returncode == 1, result.stdout + result.stderr
        output = data_root / "families" / "infra" / "runtime-v10-git-bound" / "prepost"
        receipt = json.loads((output / "execution-receipt.json").read_text())
        assert receipt["status"] == "failed"
        ledger = json.loads((data_root / "runtime/resource-ledger.json").read_text())
        assert ledger["reservations"] == []
        assert len(ledger["charges"]) == 1
        assert ledger["charges"][0]["status"] == "failed"
