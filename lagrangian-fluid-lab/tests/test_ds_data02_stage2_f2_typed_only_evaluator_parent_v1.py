from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_typed_only_evaluator_parent_v1.py"


def _load():
    spec = importlib.util.spec_from_file_location("typed_parent_test_module", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


P = _load()


def _write_json(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _typed_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    result = _write_json(tmp_path / "typed" / "typed-result.json", {"schema": "v16", "frame_observations": []})
    small = []
    for name in ("producer.json", "proof-request.json", "proof.json", "source-contract.json", "v15.json"):
        path = _write_json(tmp_path / "metadata" / name, {"name": name})
        small.append(path)
    typed = {
        "schema": P.TE_SCHEMA,
        "status": "READY_FOR_PARENT_GUARD",
        "role": "DEVELOPMENT",
        "product_mode": "TYPED_ONLY_LABELS",
        "result": {"path": str(result), "sha256": _sha(result), "bytes": result.stat().st_size},
        "producer_report": {"path": str(small[0]), "sha256": _sha(small[0])},
        "proof_request": {"path": str(small[1]), "sha256": _sha(small[1])},
        "proof": {"path": str(small[2]), "sha256": _sha(small[2])},
        "source_contract": {"path": str(small[3]), "sha256": _sha(small[3])},
        "frozen_request": {"path": str(small[4]), "sha256": _sha(small[4])},
        "model_invoked": False, "cfd_invoked": False,
        "qualification": dict(P.UNKNOWN),
    }
    typed["sha256"] = P.canonical_sha(typed)
    typed_path = _write_json(tmp_path / "requests" / "typed-request.json", typed)
    return typed_path, result, small[0]


def _parent_fixture(tmp_path: Path) -> Path:
    ledger = tmp_path / "data" / "ds-data-02" / "runtime" / "resource-ledger.json"
    external = tmp_path / "external"
    home = tmp_path / "home"
    external.mkdir(parents=True)
    home.mkdir(parents=True)
    live = {
        "deadline_utc": "2099-01-01T00:00:00+00:00",
        "limits": {"storage_policy": "home_free_floor", "home_path": str(home),
                   "home_min_free_bytes": 1, "cpu_core_seconds": 10_000_000},
        "charges": [], "reservations": [],
    }
    _write_json(ledger, live)
    value = {
        "schema": "ds02.stage2.f2-portable-executor-parent-request.v3",
        "status": "READY_FOR_PARENT_GUARD", "role": "DEVELOPMENT",
        "parent_resource_binding": {
            "ledger_path": str(ledger), "external_filesystem": str(external),
            "home_path": str(home), "home_min_free_bytes": 1,
            "storage_policy": "home_free_floor", "deadline_utc": live["deadline_utc"],
        },
        "storage_scope": {"external_filesystem": str(external)},
    }
    value["sha256"] = P.canonical_sha(value)
    return _write_json(tmp_path / "requests" / "parent-v3.json", value)


def test_build_parent_binds_typed_only_and_defers_result_content(tmp_path: Path) -> None:
    typed, result, _ = _typed_fixture(tmp_path)
    parent = _parent_fixture(tmp_path)
    output = tmp_path / "requests" / "typed-parent.json"
    built = P.build_request(
        typed_request=typed,
        parent_v3_request=parent,
        output=output,
        external_filesystem=tmp_path / "external",
        ledger=tmp_path / "data" / "ds-data-02" / "runtime" / "resource-ledger.json",
        parent_attempt_id="typed-only-test-001",
        supervisor_output_root=tmp_path / "external" / "attempt",
        home_receipt=tmp_path / "home" / "receipt.json",
        python_executable=Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"),
        max_wall_seconds=30.0, external_bytes=1024 * 1024,
    )
    assert built["status"] == "READY_FOR_PARENT_GUARD"
    request = json.loads(output.read_text(encoding="utf-8"))
    assert request["product_mode"] == "TYPED_ONLY_LABELS"
    assert request["credit_boundary"]["raw_to_typed_credit"] == "NOT_CLAIMED"
    assert request["typed_request"]["sha256"] == _sha(typed)
    assert request["static_bindings"]
    assert P._validate_request(output)["typed"]["result"]["bytes"] == result.stat().st_size


def test_parent_rejects_raw_product_mode(tmp_path: Path) -> None:
    typed, _, _ = _typed_fixture(tmp_path)
    value = json.loads(typed.read_text(encoding="utf-8"))
    value["product_mode"] = "RAW_TO_TYPED_TO_LABEL"
    value["sha256"] = P.canonical_sha(value)
    typed.write_text(json.dumps(value) + "\n", encoding="utf-8")
    with pytest.raises(P.TypedParentError, match="TYPED_ONLY_LABELS"):
        P._load_typed_request(typed)
