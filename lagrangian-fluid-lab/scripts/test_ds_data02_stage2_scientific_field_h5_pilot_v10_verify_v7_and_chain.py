#!/usr/bin/env python3
"""Additive V7 verifier and genuine isolated V10/V3/V5 chain tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
PRIMARY_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
PRIMARY_SCRIPTS = PRIMARY_ROOT / "lagrangian-fluid-lab/scripts"
PRIMARY_VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
CHAIN = HERE / "ds_data02_stage2_scientific_field_h5_runtime_v10_chain_v1.py"
V7 = HERE / "ds_data02_stage2_scientific_field_h5_pilot_v10_verify_v7.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PREP_TEST = _load(
    "pilot_v10_prepare_v3_test_for_v7",
    HERE / "test_ds_data02_stage2_scientific_field_h5_pilot_v10_prepare_v3.py",
)
V7_MODULE = _load("pilot_v10_verify_v7_test_module", V7)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _copy_runtime_closure(destination: Path) -> dict[str, Path]:
    names = (
        "ds_data02_runtime_v10_git_bound.py",
        "ds_data02_runtime_v9_git_bound.py",
        "ds_data02_runtime_v8.py",
        "ds_data02_runtime_v6.py",
        "ds_data02_runtime_v2.py",
        "ds_data02_git_launch_state_v1.py",
        "ds_data02_git_launch_state_v2.py",
        "ds_data02_git_launch_state_v3.py",
        "ds_data02_stage2_scientific_field_h5_audit_v3.py",
        "ds_data02_stage2_verify_scientific_field_h5_audit_v5.py",
    )
    scripts = destination / "lagrangian-fluid-lab/scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    result: dict[str, Path] = {}
    for name in names:
        source = PRIMARY_SCRIPTS / name
        if not source.is_file():
            raise unittest.SkipTest(f"primary V3 source is unavailable: {source}")
        target = scripts / name
        shutil.copy2(source, target)
        result[name] = target
    return result


def _init_git(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "fixture"], cwd=root, check=True)
    scope = root / "scope.txt"
    scope.write_text("bounded input scope\n", encoding="utf-8")
    subprocess.run(["git", "add", "scope.txt"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "tiny runtime fixture"], cwd=root, check=True)


def _write_ledger(data_root: Path) -> None:
    runtime = data_root / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    ledger = {
        "deadline_utc": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "limits": {
            "gpu_seconds": 0,
            "cpu_core_seconds": 120,
            "new_storage_bytes": 64 * 1024 * 1024,
            "qualification_attempts": 0,
            "production_attempts": 0,
            "storage_policy": "home_free_floor",
            "home_min_free_bytes": 0,
        },
        "charges": [],
        "reservations": [],
        "attempts": [],
    }
    (runtime / "resource-ledger.json").write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")


def _tiny_request(repo: Path, data_root: Path, copied: dict[str, Path], manifest: Path) -> Path:
    scope = repo / "scope.txt"
    static_paths = [Path(ref["path"]).resolve() for ref in json.loads(manifest.read_text(encoding="utf-8"))["static_source_refs"]]
    paths: list[Path] = [*copied.values(), manifest, scope, *static_paths]
    unique: list[Path] = []
    for path in paths:
        path = path.resolve()
        if path not in unique:
            unique.append(path)
    runtime = copied["ds_data02_runtime_v10_git_bound.py"]
    worker = copied["ds_data02_stage2_scientific_field_h5_audit_v3.py"]
    request = {
        "schema": "ds02.request.v1",
        "family_id": "F1",
        "case_id": "tiny_audit",
        "attempt_id": "tiny_audit_001",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 60,
        "max_memory_bytes": 512 * 1024 * 1024,
        "estimated_peak_memory_bytes": 512 * 1024 * 1024,
        "estimated_storage_bytes": 16 * 1024 * 1024,
        "cwd": str(repo),
        "worktree_root": str(repo),
        "command": [
            str(PRIMARY_VENV), "-B", str(worker), "audit", "--manifest", str(manifest),
            "--output", "{attempt_root}/report.json", "--chunk", "2",
        ],
        "input_files": [str(path) for path in unique],
        "input_sha256": {str(path): sha256(path) for path in unique},
        "git_snapshot_timeout_seconds": 2,
        "interpreter_binding": {"literal_path": str(PRIMARY_VENV)},
    }
    path = repo / "request.json"
    path.write_text(json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


class ScientificFieldH5PilotV7Tests(unittest.TestCase):
    def test_real_v3_index_passes_v7_and_missing_runtime_role_fails(self) -> None:
        builder = PREP_TEST.PilotV10V3Tests()
        root, args = builder._builder_fixture()
        old_prep_sha = PREP_TEST.PREP.CURRENT_SHA256
        old_v7_sha = V7_MODULE.BASE.CURRENT_SHA256
        try:
            result = PREP_TEST.PREP.prepare(args)
            V7_MODULE.BASE.CURRENT_SHA256 = PREP_TEST.sha256(root / "current.json")
            output = root / "v7-report.json"
            verified = V7_MODULE.verify(Path(result["index"]), output)
            self.assertEqual(verified["runtime_role_count"], 11)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["schema"], "ds02.stage2.scientific-field-h5-pilot-v7-verification.v1")
            self.assertFalse(report["production_eligible"])
            request_row = json.loads(Path(result["index"]).read_text(encoding="utf-8"))["requests"][0]
            request_path = Path(request_row["request"]["path"])
            request = json.loads(request_path.read_text(encoding="utf-8"))
            request["runtime_binding"].pop("runtime_v2")
            request_path.write_text(json.dumps(request, sort_keys=True) + "\n", encoding="utf-8")
            index = json.loads(Path(result["index"]).read_text(encoding="utf-8"))
            index["requests"][0]["request"]["sha256"] = sha256(request_path)
            Path(result["index"]).write_text(json.dumps(index, sort_keys=True) + "\n", encoding="utf-8")
            with self.assertRaises(V7_MODULE.PilotVerificationV7Error):
                V7_MODULE.verify(Path(result["index"]), root / "v7-negative.json")
        finally:
            PREP_TEST.PREP.CURRENT_SHA256 = old_prep_sha
            V7_MODULE.BASE.CURRENT_SHA256 = old_v7_sha
            shutil.rmtree(root, ignore_errors=True)

    def test_real_v10_cli_worker_v3_and_independent_v5_complete_isolated_chain(self) -> None:
        if not PRIMARY_VENV.is_file():
            self.skipTest(f"literal primary venv is unavailable: {PRIMARY_VENV}")
        with tempfile.TemporaryDirectory(prefix="ds02-v10-v3-v5-chain-") as raw:
            root = Path(raw)
            repo = root / "repo"
            repo.mkdir()
            copied = _copy_runtime_closure(repo)
            fixture = repo / "fixture"
            fixture.mkdir()
            h5_path = fixture / "fixture.h5"
            v4_test = _load(
                "v4_helpers_for_v10_chain",
                PRIMARY_SCRIPTS / "test_ds_data02_stage2_verify_scientific_field_h5_audit_v4_cli.py",
            )
            v4_test.BASE.write_h5(h5_path)
            manifest = v4_test.write_metadata_chain(fixture, h5_path)
            _init_git(repo)
            data_root = root / "data"
            data_root.mkdir()
            _write_ledger(data_root)
            request = _tiny_request(repo, data_root, copied, manifest)
            output = root / "chain-result.json"
            command = [
                str(PRIMARY_VENV), "-B", str(CHAIN), "run",
                "--request", str(request), "--data-root", str(data_root),
                "--runtime-v10", str(copied["ds_data02_runtime_v10_git_bound.py"]),
                "--worker", str(copied["ds_data02_stage2_scientific_field_h5_audit_v3.py"]),
                "--verifier", str(copied["ds_data02_stage2_verify_scientific_field_h5_audit_v5.py"]),
                "--output", str(output), "--allow-fixture-context",
            ]
            result = subprocess.run(command, text=True, capture_output=True, timeout=120, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            chain = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(chain["status"], "COMPLETED_TINY_V10_WORKER_V3_V5_CHAIN_NO_SCIENTIFIC_CREDIT")
            self.assertFalse(chain["production_eligible"])
            self.assertFalse(chain["model_invoked"])
            receipt_path = Path(chain["runtime_v10"]["receipt_path"])
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "completed")
            verified = json.loads(Path(chain["verifier_v5"]["output"]).read_text(encoding="utf-8"))
            self.assertFalse(verified["scientific_credit"])
            ledger = json.loads((data_root / "runtime/resource-ledger.json").read_text(encoding="utf-8"))
            self.assertEqual(ledger["reservations"], [])
            self.assertEqual(len(ledger["charges"]), 1)

            # The same real chain must not silently convert a TEST_ONLY
            # fixture into a production result when the V5 opt-in is absent.
            second_data = root / "data-no-fixture"
            second_data.mkdir()
            _write_ledger(second_data)
            rejected_output = root / "rejected-chain.json"
            rejected = subprocess.run(
                [*command[: command.index("--data-root")], "--data-root", str(second_data), *command[command.index("--runtime-v10"): command.index("--allow-fixture-context")], "--output", str(rejected_output)],
                text=True, capture_output=True, timeout=120, check=False,
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertFalse(rejected_output.exists())


if __name__ == "__main__":
    unittest.main()
