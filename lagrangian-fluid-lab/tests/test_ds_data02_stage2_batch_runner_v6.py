from __future__ import annotations

import hashlib
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SCRIPT = SCRIPTS / "ds_data02_batch_runner_v6.py"
spec = importlib.util.spec_from_file_location("batch_runner_v6_manufactured_test", SCRIPT)
assert spec is not None and spec.loader is not None
sys.path.insert(0, str(SCRIPTS))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_v6_batch_dispatches_one_manufactured_cpu_request(tmp_path: Path) -> None:
    data_root = tmp_path / "data-root"
    (data_root / "runtime").mkdir(parents=True)
    ledger = {
        "schema": "ds02.resource-ledger.v1",
        "deadline_utc": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "limits": {
            "gpu_seconds": 0.0,
            "cpu_core_seconds": 1000.0,
            "new_storage_bytes": 100_000,
            "qualification_attempts": 1,
            "production_attempts": 1,
            "storage_policy": "home_free_floor",
            "home_min_free_bytes": 1,
        },
        "charges": [],
        "reservations": [],
        "attempts": [],
    }
    (data_root / "runtime/resource-ledger.json").write_text(json.dumps(ledger))

    worker = tmp_path / "manufactured-worker.py"
    worker.write_text("print('v6-batch-ok')\n")
    inputs = [*module.BOUND_RUNNER_FILES, worker, Path(sys.executable).resolve()]
    request = {
        "family_id": "infra",
        "case_id": "manufactured-v6-batch",
        "attempt_id": "batch-001",
        "kind": "cpu",
        "cpu_task_kind": "tests",
        "command": [sys.executable, str(worker)],
        "cwd": str(ROOT),
        "max_wall_seconds": 30,
        "cpu_threads": 1,
        "estimated_storage_bytes": 64_000,
        "input_files": [str(path.resolve()) for path in inputs],
        "input_sha256": {str(path.resolve()): _sha(path.resolve()) for path in inputs},
        "worktree_root": str(ROOT),
    }
    request_path = tmp_path / "manufactured-v6-batch.json"
    request_path.write_text(json.dumps(request))

    output_dir = tmp_path / "batch-receipt"
    result = module.run_batch(
        [request_path], max_concurrency=1, label="manufactured-v6", data_root=data_root,
        output_dir=output_dir,
    )

    assert result == 0
    summary = json.loads((output_dir / "batch-receipt.json").read_text())
    assert summary["status"] == "completed"
    assert len(summary["completed"]) == 1
    receipt_path = data_root / "families/infra/manufactured-v6-batch/batch-001/execution-receipt.json"
    receipt = json.loads(receipt_path.read_text())
    assert receipt["status"] == "completed"
    assert receipt["runner_source"].endswith("ds_data02_runtime_v6.py")
    final_ledger = json.loads((data_root / "runtime/resource-ledger.json").read_text())
    assert final_ledger["reservations"] == []
    assert len(final_ledger["charges"]) == 1
    assert final_ledger["charges"][0]["status"] == "completed"

