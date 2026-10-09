#!/usr/bin/env python3
"""Exercise the real ROOT279 guard into the common-endpoint consumer.

The older common-endpoint self-test manufactured a guarded-result JSON
directly.  This fixture closes that gap without touching production files: it
creates ten tiny Part sources, invokes the actual ROOT279 CLI wrapper (which
invokes the V4 guard and a child worker in a new process), then points the
common-endpoint observer at the guard's actual result and actual child output.
The child report is deliberately a tiny manufactured observer report, so no
native payload or solver is involved.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
GUARDED = HERE / "stage2_f1_s2_root279_pair_native_observer_guarded_v1.py"
V4_PATH = HERE / "stage2_f1_native_selected_observer_guarded_v4.py"
COMMON_PATH = HERE / "stage2_f1_s2_root279_common_endpoint_observer_v1.py"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _record(path: Path) -> dict[str, Any]:
    stat = path.stat()
    raw = path.read_bytes()
    return {"path": str(path.absolute()), "sha256": hashlib.sha256(raw).hexdigest(),
            "stat": {"device": stat.st_dev, "inode": stat.st_ino, "bytes": stat.st_size,
                     "mtime_ns": stat.st_mtime_ns, "ctime_ns": stat.st_ctime_ns}}


def _child_worker(path: Path, child_source: Path) -> None:
    # The guard's child interface is the same one used by V1: the source
    # manifest is passed in, and the child writes the result path.  The
    # observer report itself is manufactured JSON, not a native decode.
    path.write_text(
        "import argparse, json, pathlib, shutil\n"
        "p=argparse.ArgumentParser(); p.add_argument('--manifest'); p.add_argument('--attempt-root'); p.add_argument('--output'); a=p.parse_args()\n"
        f"source=pathlib.Path({str(child_source)!r})\n"
        "m=json.loads(pathlib.Path(a.manifest).read_text()); c=m['cases'][0]\n"
        "pathlib.Path(c['scratch_root'].replace('{attempt_root}', a.attempt_root)).mkdir(parents=True, exist_ok=True)\n"
        "pathlib.Path(a.output).parent.mkdir(parents=True, exist_ok=True)\n"
        "shutil.copyfile(source, a.output)\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _join_actual_guard(common_manifest: dict[str, Any], guard_output: Path, child_output: Path) -> dict[str, Any]:
    value = json.loads(json.dumps(common_manifest))
    sources = value["sources"]
    sources["root279_guard_result"] = _record(guard_output)
    sources["root279_child_report"] = _record(child_output)
    return value


def self_test() -> None:
    v4 = _load(V4_PATH, "stage2_root279_guarded_common_v4_fixture")
    common = _load(COMMON_PATH, "stage2_root279_common_endpoint_fixture")
    # The additive ROOT279 wrapper configures its imported V4 to ten records;
    # use the same cardinality to create the actual CLI input manifest.
    v4.EXPECTED_DEFERRED_COUNT = 10
    with tempfile.TemporaryDirectory(prefix="root279-guarded-common-fixture-") as directory:
        root = Path(directory)
        (root / "common").mkdir(parents=True, exist_ok=True)
        common_manifest_path, _ = common._fixture_manifest(root / "common")
        common_manifest = json.loads(common_manifest_path.read_text(encoding="utf-8"))
        common_child = root / "common" / "child.json"
        fake_child = root / "guard" / "common-child-worker.py"
        fake_child.parent.mkdir(parents=True, exist_ok=True)
        _child_worker(fake_child, common_child)

        guard_manifest, _ = v4._fixture_manifest(root / "guard" / "source")
        attempt = root / "guard" / "attempt"
        guard_output = attempt / "observer" / "root279-guard-result.json"
        command = [str(PYTHON), str(GUARDED), "--run", "--manifest", str(guard_manifest),
                   "--attempt-root", str(attempt), "--output", str(guard_output),
                   "--v1-worker", str(fake_child), "--python", str(PYTHON),
                   "--cwd", str(root), "--timeout-seconds", "20"]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=30)
        if completed.returncode != 0 or not guard_output.is_file():
            raise AssertionError(f"ROOT279 guarded CLI failed: rc={completed.returncode}; stdout={completed.stdout}; stderr={completed.stderr}")
        guarded_result = json.loads(guard_output.read_text(encoding="utf-8"))
        if not guarded_result.get("status", "").startswith("PASS") or guarded_result.get("scope", {}).get("deferred_native_count") != 10:
            raise AssertionError(f"ROOT279 guard did not pass ten-file scope: {guarded_result}")
        child_output = attempt / "observer" / ".v1-result.json"
        if not child_output.is_file():
            raise AssertionError("ROOT279 guard did not produce its actual child report")

        joined = _join_actual_guard(common_manifest, guard_output, child_output)
        joined_path = root / "common" / "guarded-joined-manifest.json"
        joined_path.write_text(json.dumps(joined, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        endpoint_output = root / "common" / "endpoint-result.json"
        result = common.run(joined_path, endpoint_output)
        if result.get("status") != common.PASS_STATUS:
            raise AssertionError(f"common endpoint rejected actual guard result: {result}")
        if result.get("scientific_qualification", {}).get("credit") != 0:
            raise AssertionError("fixture granted scientific credit")
    print("PASS_ROOT279_GUARDED_CLI_TO_COMMON_ENDPOINT_FIXTURE")


if __name__ == "__main__":
    self_test()
