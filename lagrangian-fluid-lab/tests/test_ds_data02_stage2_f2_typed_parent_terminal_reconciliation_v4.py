from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_typed_parent_terminal_reconciliation_v4.py"
RUNTIME_V6 = ROOT / "scripts/ds_data02_runtime_v6.py"


def _load(path: Path):
    spec = importlib.util.spec_from_file_location("typed_parent_reconciliation_v4_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M = _load(SCRIPT)


def _bound_fixture(tmp_path: Path) -> dict:
    data_root = tmp_path / "data-root"
    runtime = data_root / "runtime"
    runtime.mkdir(parents=True)
    external = tmp_path / "external"
    output_root = external / "attempt"
    output_root.mkdir(parents=True)
    (output_root / "worker.log").write_bytes(b"worker")
    trace = output_root / "trace"
    trace.write_bytes(b"trace")
    home = tmp_path / "home"
    home.mkdir()
    receipt = home / "receipt.json"
    receipt.write_bytes(b"receipt")
    ledger = runtime / "resource-ledger.json"
    ledger.write_text(json.dumps({
        "deadline_utc": "2099-01-01T00:00:00+00:00",
        "limits": {
            "home_path": str(home), "storage_policy": "home_free_floor",
            "home_min_free_bytes": 0, "cpu_core_seconds": 1000,
            "gpu_seconds": 1000, "new_storage_bytes": 10**12,
            "qualification_attempts": 100, "production_attempts": 100,
        },
        "attempts": [], "charges": [], "reservations": [],
    }) + "\n", encoding="utf-8")
    request_path = tmp_path / "request.json"
    request = {
        "typed_request": {"path": str(request_path)},
        "storage_scope": {"external_min_free_bytes": 0},
    }
    request_path.write_text(json.dumps(request) + "\n", encoding="utf-8")
    return {
        "path": request_path, "request": request, "ledger": ledger,
        "limits": {"home_path": str(home), "home_min_free_bytes": 0},
        "external": external, "output_root": output_root, "receipt": receipt,
        "trace_path": trace, "runtime_path": RUNTIME_V6,
        "runtime_sha": M.sha256_file(RUNTIME_V6),
        "parent_attempt_id": "typed-v6-root-078-v3-test",
        "reservation_id": "typed-v6-root-078-v3-test::reservation",
        "charge_id": "typed-v6-root-078-v3-test::charge",
        "max_wall": 900.0, "cleanup_grace": 25.0,
        "external_estimate": 1000, "home_estimate": 100,
        "allow_missing_parent": False,
    }


def test_real_p1_bound_adapter_preserves_cleanup_contract(tmp_path: Path) -> None:
    bound = _bound_fixture(tmp_path)
    adapted = M.V6.V4.P1._bound_for_parent(bound)
    assert adapted["runtime_path"] == bound["runtime_path"]
    assert adapted["executor_path"] == bound["request"]["typed_request"]["path"]
    assert adapted["max_wall"] == 900.0
    assert adapted["cleanup_grace"] == 25.0
    assert adapted["request"] is bound["request"]


def test_real_parent_charge_accepts_scoped_missing_parent_without_mock(tmp_path: Path) -> None:
    bound = _bound_fixture(tmp_path)
    adapted = M.V6.V4.P1._bound_for_parent(bound)
    result = M.PARENT._charge(
        adapted, status="failed", cpu_seconds=1.25,
        external_bytes=sum(p.stat().st_size for p in bound["output_root"].iterdir()),
        home_bytes=bound["receipt"].stat().st_size,
        trace_bytes=bound["trace_path"].stat().st_size,
        copy_hash_bytes=0, allow_missing_parent=True)
    assert result["status"] == "PARENT_CHARGE_APPLIED"
    ledger = json.loads(bound["ledger"].read_text(encoding="utf-8"))
    rows = [row for row in ledger["charges"] if row.get("id") == bound["charge_id"]]
    assert len(rows) == 1
    assert rows[0]["parent_missing_fallback"] is True
    assert rows[0]["cpu_core_seconds"] == 1.25


def test_consumed_root078_load_reaches_real_p1_adapter_without_mutation() -> None:
    """Exercise the actual ROOT078 request, not a hand-built bound mapping."""
    request_path = Path(
        "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/evaluator/v6/"
        "f2-s1-typed-evaluator-parent-v6-current-root-078-001.json"
    )
    if not request_path.is_file():
        pytest.skip("ROOT078 consumed request is unavailable in this checkout")
    request, bound, _live = M._load_bound_request(request_path)
    before = M.sha256_file(bound["ledger"])
    adapted = M.V6.V4.P1._bound_for_parent(bound)
    after = M.sha256_file(bound["ledger"])
    assert before == after
    assert adapted["cleanup_grace"] >= 20.0
    assert adapted["external_estimate"] == int(request["storage_scope"]["external_reservation_bytes"])
    assert adapted["home_estimate"] == int(request["storage_scope"]["home_receipt_bytes"])
    assert adapted["allow_missing_parent"] is False
    assert adapted["reservation_id"] == request["parent_resource_binding"]["reservation_id"]
    assert adapted["charge_id"] == request["parent_resource_binding"]["charge_id"]
