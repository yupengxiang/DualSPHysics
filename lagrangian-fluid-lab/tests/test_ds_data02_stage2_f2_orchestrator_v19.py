from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pytest


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import ds_data02_stage2_f2_portable_orchestrator_v19 as worker  # noqa: E402


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _request(tmp_path: Path) -> dict:
    source = tmp_path / "v15.json"
    source.write_text(json.dumps({"schema": "ds02.stage2.f2-s1-replay-request.v15"}) + "\n")
    sidecar = tmp_path / "sidecar.json"
    sidecar.write_text(json.dumps({"schema": "sidecar"}) + "\n")
    return {
        "schema": worker.REQUEST_SCHEMA,
        "orchestration_schema": worker.ORCHESTRATION_SCHEMA,
        "source_bindings": {
            "v15_replay_request": {"path": str(source), "sha256": _sha(source)},
            "v16_flux_forward_sidecar": {"path": str(sidecar), "sha256": _sha(sidecar)},
        },
        "model_invoked": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def test_request_rejects_v12_shared_schema_substitution(tmp_path: Path) -> None:
    request = _request(tmp_path)
    request["schema"] = "ds02.stage2.f2-s1-replay-request.v12"
    with pytest.raises(worker.OrchestrationV19Error, match="ds02.request.v1"):
        worker._require_request(request)


def test_source_binding_hash_mutation_is_rejected(tmp_path: Path) -> None:
    request = _request(tmp_path)
    request["source_bindings"]["v15_replay_request"]["sha256"] = "0" * 64
    with pytest.raises(worker.OrchestrationV19Error, match="SHA differs"):
        worker._source_ref(request, "v15_replay_request")


def test_execution_closure_records_v11_v12_as_nonruntime_and_raw_gap() -> None:
    closure = worker._execution_closure()
    assert "NOT_IMPORTED" in closure["historical_v11_v12"]["v11"]
    assert "v12 request schema is rejected" in closure["historical_v11_v12"]["v12"]
    assert {item["module"] for item in closure["installed_dependencies"]} == {"numpy", "h5py"}

