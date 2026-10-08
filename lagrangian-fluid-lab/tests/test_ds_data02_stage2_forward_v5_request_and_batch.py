from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
REQUEST_BUILDER = ROOT / "scripts/ds_data02_stage2_forward_request_v5.py"
BATCH = ROOT / "scripts/ds_data02_batch_runner_v5.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_forward_builder_reuses_source_hashes_and_adds_v5_closure(tmp_path: Path) -> None:
    builder = _load("forward_v5_test_module", REQUEST_BUILDER)
    inherited = ROOT / "scripts" / "ds_data02_runtime_v2.py"
    source = {
        "family_id": "F3",
        "case_id": "CASE_A",
        "attempt_id": "scan-F3-v4-001",
        "input_files": [str(inherited)],
        "input_sha256": {str(inherited): builder.sha256_file(inherited)},
        "model_invoked": False,
        "cfd_invoked": False,
    }
    source_path = tmp_path / "source.json"
    source_path.write_text(json.dumps(source))
    output = tmp_path / "forward.json"
    forwarded = builder.build(source_path, output, shared_root=ROOT.parent,
                              attempt_id="scan-F3-v5-001")
    assert forwarded["attempt_id"] == "scan-F3-v5-001"
    assert forwarded["forward_v5"]["inherited_input_sha256_reused"] is True
    assert len(forwarded["forward_v5"]["guard_closure"]) == 5
    assert all(str(item["path"]) in forwarded["input_sha256"] for item in forwarded["forward_v5"]["guard_closure"])
    assert forwarded["qualification"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


def test_forward_builder_rejects_mutable_batch_receipt(tmp_path: Path) -> None:
    builder = _load("forward_v5_reject_test_module", REQUEST_BUILDER)
    mutable = tmp_path / "batch-receipt.json"
    mutable.write_text("{}")
    source = {
        "family_id": "F3",
        "case_id": "CASE_A",
        "attempt_id": "scan-F3-v4-001",
        "input_files": [str(mutable)],
        "input_sha256": {str(mutable): builder.sha256_file(mutable)},
    }
    source_path = tmp_path / "source.json"
    source_path.write_text(json.dumps(source))
    with pytest.raises(builder.ForwardRequestError, match="mutable batch receipt"):
        builder.build(source_path, tmp_path / "forward.json", shared_root=ROOT.parent)


def test_batch_v5_preflight_requires_each_current_guard(tmp_path: Path) -> None:
    builder = _load("forward_v5_batch_builder_module", REQUEST_BUILDER)
    batch = _load("batch_v5_test_module", BATCH)
    inherited = ROOT / "scripts" / "ds_data02_runtime_v2.py"
    source = {
        "family_id": "F7",
        "case_id": "CASE_B",
        "attempt_id": "scan-F7-v4-001",
        "input_files": [str(inherited)],
        "input_sha256": {str(inherited): builder.sha256_file(inherited)},
    }
    source_path = tmp_path / "source.json"
    source_path.write_text(json.dumps(source))
    forwarded_path = tmp_path / "forward.json"
    builder.build(source_path, forwarded_path, shared_root=ROOT.parent,
                  attempt_id="scan-F7-v5-001")
    value = batch._preflight_request(forwarded_path)
    assert value["attempt_id"] == "scan-F7-v5-001"
    bad = json.loads(forwarded_path.read_text())
    bound = str(batch.BOUND_RUNNER_FILES[0])
    bad["input_sha256"][bound] = "0" * 64
    bad_path = tmp_path / "bad.json"
    bad_path.write_text(json.dumps(bad))
    with pytest.raises(ValueError, match="current guard closure"):
        batch._preflight_request(bad_path)
