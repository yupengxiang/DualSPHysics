"""Bounded metadata tests for the ROOT140 post-terminal V2 contract."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_root140_postterminal_contract_v2.py"
PREP = ROOT / "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v53-root140-source-prepared-20261009"
ROOT_TREE = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
ACTUAL = ROOT_TREE / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v53-root-forward-140-001"


def _load():
    spec = importlib.util.spec_from_file_location("root140_contract_v2_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


B = _load()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _paths() -> dict[str, Path]:
    return {
        "executor": PREP / "f2-s1-root140-v53-executor-request.json",
        "parent": PREP / "f2-s1-root140-parent-v53-request.json",
        "preflight": PREP / "f2-s1-root140-v53-metadata-preflight.json",
        "postterminal": PREP / "f2-s1-root140-v53-postterminal-guard-request.json",
        "actual_parent": ACTUAL / "f2-s1-portable-parent-request-v53-root-140.json",
        "actual_preflight": ACTUAL / "ROOT140_V53_ACTUAL_PARENT_METADATA_VERIFICATION.json",
    }


def test_prepare_binds_actual_forward_parent_and_keeps_postterminal_artifacts_pending(tmp_path: Path) -> None:
    p = _paths()
    assert all(path.is_file() for path in p.values())
    output = tmp_path / "root140-v55-contract.json"
    result = B.prepare(
        executor_request=p["executor"], parent_request=p["parent"],
        preflight=p["preflight"], postterminal_request=p["postterminal"],
        actual_parent_request=p["actual_parent"], actual_preflight=p["actual_preflight"],
        output=output)
    value = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == B.PREPARED_STATUS
    assert value["schema"] == "ds02.stage2.f2-root140-postterminal-executable-contract.v2"
    assert value["status"] == "PREPARED_PENDING_PARENT_TERMINAL"
    assert value["payload_read_during_prepare"] is False
    assert value["qualification"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    launch = value["actual_launch_binding"]
    assert launch["parent_request"]["physical_sha256"] == _sha(p["actual_parent"])
    assert launch["metadata_preflight"]["physical_sha256"] == _sha(p["actual_preflight"])
    assert value["runtime_closure"]["role_count"] == 34
    assert value["runtime_closure"]["literal_interpreter"]["argv0"].endswith("/.venv/bin/python")
    assert all(row["source_path_fallback"] == "FORBIDDEN" for row in value["runtime_closure"]["roles"])
    assert "--parent-receipt" in value["commands"]["postterminal_split_parent_and_returned_report"]
    assert "--home-receipt" not in value["commands"]["postterminal_split_parent_and_returned_report"]
    assert all(item["status"] == "PENDING" for item in value["required_terminal_artifacts"].values())
    assert not (tmp_path / "target").exists()


def test_actual_metadata_evidence_cannot_be_rebound_to_another_parent(tmp_path: Path) -> None:
    p = _paths()
    evidence = json.loads(p["actual_preflight"].read_text(encoding="utf-8"))
    evidence["request_sha256"] = "0" * 64
    wrong = tmp_path / "wrong-preflight.json"
    wrong.write_text(json.dumps(evidence, sort_keys=True), encoding="utf-8")
    with pytest.raises(B.ContractError, match="not bound to the actual parent"):
        B._actual_launch_inputs(
            parent_request=p["actual_parent"], metadata_preflight=wrong,
            expected_executor_sha=_sha(p["executor"]),
        )


def test_bind_requires_completed_terminal_records(tmp_path: Path) -> None:
    p = _paths()
    prepared = tmp_path / "prepared.json"
    B.prepare(
        executor_request=p["executor"], parent_request=p["parent"],
        preflight=p["preflight"], postterminal_request=p["postterminal"],
        actual_parent_request=p["actual_parent"], actual_preflight=p["actual_preflight"],
        output=prepared)
    # Do not fabricate a receipt or a product: the contract must fail closed
    # before any terminal binding is attempted.
    with pytest.raises((B.ContractError, OSError)):
        B.bind_terminal(
            prepared_contract=prepared,
            parent_receipt=tmp_path / "missing-home-receipt.json",
            returned_parent_report=tmp_path / "missing-returned-report.json",
            worker_report=tmp_path / "missing-worker.json",
            source_contract=tmp_path / "missing-source-contract.json",
            current_runtime_view=tmp_path / "missing-current-view.json",
            relocated_v15_request=tmp_path / "missing-v15.json",
            engine_report=tmp_path / "missing-engine.json",
            output=tmp_path / "bound.json",
        )
