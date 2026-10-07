from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")


def test_v24_relocated_runner_imports_transitive_closure_in_real_subprocess(tmp_path: Path) -> None:
    """Exercise the failed v23 boundary with actual copied runtime files.

    The subprocess has only the new overlay directories on its import path;
    no original checkout directory is made available as a fallback.  It stops
    after loading portable/replay modules, so it performs no H5/BI4 read.
    """
    runtime = tmp_path / "bundle" / "runtime"
    portable = runtime / "portable"
    replay = runtime / "replay"
    portable.mkdir(parents=True)
    replay.mkdir(parents=True)
    for name in (
        "ds_data02_stage2_f2_portable_v24.py",
        "ds_data02_stage2_f2_portable_v16.py",
    ):
        shutil.copyfile(SCRIPTS / name, portable / name)
    for name in (
        "ds_data02_stage2_f2_replay_runner_v24.py",
        "ds_data02_stage2_f2_replay_v15.py",
        "ds_data02_stage2_f2_replay_v14.py",
    ):
        shutil.copyfile(SCRIPTS / name, replay / name)
    runner = replay / "ds_data02_stage2_f2_replay_runner_v24.py"
    code = """
import importlib.util
from pathlib import Path
runner_path = Path.cwd() / 'bundle/runtime/replay/ds_data02_stage2_f2_replay_runner_v24.py'
spec = importlib.util.spec_from_file_location('relocated_v24_runner', runner_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
portable = module._load_portable()
replay = module._load_replay()
assert portable.PROFILE_SCHEMA.endswith('.v24')
assert replay.REQUEST_SCHEMA.endswith('.v15')
print('TRANSITIVE_V24_CLOSURE_OK')
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = ""
    result = subprocess.run(
        [str(PYTHON), "-c", code], cwd=tmp_path, env=env,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "TRANSITIVE_V24_CLOSURE_OK" in result.stdout
    assert runner.is_file()
