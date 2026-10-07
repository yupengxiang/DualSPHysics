from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts/ds_data02_stage2_f2_replay_runner_v27.py"
BUILDER = ROOT / "scripts/ds_data02_stage2_f2_typed_replay_request_v27.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = _load(RUNNER, "typed_replay_runner_v27_test_module")
builder = _load(BUILDER, "typed_replay_request_v27_test_module")

V26_REQUEST = ROOT / (
    "campaigns/ds-data-02/stage2/replay/v26/"
    "f2-s1-portable-typed-only-full401-replay-request-v26-001.json"
)
V26_RECEIPT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/"
    "F2_S1_PORTABLE_TYPED_ONLY_FULL401_REPLAY_V26/"
    "f2-s1-portable-typed-only-full401-v26-primary-001/execution-receipt.json"
)
V26_RESULT = V26_RECEIPT.with_name("f2-s1-typed-only-full401-result-v26.json")


def test_v27_repair_accepts_complete_v26_result_without_hdf5_scope(tmp_path: Path) -> None:
    report = runner.repair(V26_REQUEST, V26_RECEIPT, V26_RESULT, tmp_path / "repair.json")
    assert report["status"].startswith("REUSED_V26_FULL401_OUTPUT")
    assert report["execution_boundary"] == {
        "cfd_invoked": False,
        "model_invoked": False,
        "original_path_fallback": "FORBIDDEN",
        "repair_reads_bi4": False,
        "repair_reads_hdf5": False,
        "repair_reruns_full401": False,
        "reused_immutable_result": True,
    }
    assert report["result_contract"]["frames"] == 401
    assert report["result_contract"]["fluid_labels"] == 21114
    assert report["inherited_hdf5"]["content_hash_source"] == "v26_parent_receipt_after_run"


def test_v27_request_is_cpu_only_reuse_and_canonical(tmp_path: Path) -> None:
    value = builder.build_request(
        V26_REQUEST,
        V26_RECEIPT,
        V26_RESULT,
        RUNNER,
        tmp_path / "request.json",
    )
    assert value["schema"] == "ds02.request.v1"
    assert value["orchestration_schema"] == builder.ORCHESTRATION_SCHEMA
    assert value["status"] == "READY_FOR_PARENT_CPU_SLOT"
    assert value["reuse_scope"]["full401_calculation_rerun"] is False
    assert value["execution_contract"]["hdf5_or_bi4_read"] is False
    assert value["resource_request"]["hdf5_bytes_read"] == 0
    assert value["resource_request"]["bi4_bytes_read"] == 0
    assert "--io-slot-approved" not in value["command"]
    assert value["sha256"] == builder.canonical_sha(value)


def test_v27_rejects_a_promoted_or_incomplete_v26_request(tmp_path: Path) -> None:
    original = json.loads(V26_REQUEST.read_text())
    bad = copy.deepcopy(original)
    bad["qualification"] = {"QI": "QN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    bad["sha256"] = builder.canonical_sha(bad)
    bad_path = tmp_path / "bad-v26.json"
    bad_path.write_text(json.dumps(bad))
    try:
        builder.build_request(bad_path, V26_RECEIPT, V26_RESULT, RUNNER, tmp_path / "reject.json")
    except builder.TypedReplayV27RequestError as error:
        assert "immutable development" in str(error)
    else:
        raise AssertionError("promoted v26 request must be rejected")

