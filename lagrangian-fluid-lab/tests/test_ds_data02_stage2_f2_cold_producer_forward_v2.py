from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_cold_producer_forward_v2.py"
SIDECAR = ROOT / "campaigns/ds-data-02/stage2/evaluator/v3/f2-s1-current-source-rebind-v1-001.json"
V39_CONTRACT = ROOT / "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v38-full-chain/f2-s1-fresh-v16-source-contract-v3-001.json"
V15_REQUEST = ROOT / "campaigns/ds-data-02/stage2/replay/v15/f2-s1-replay-request-v15-001.json"


def _load(path: Path):
    spec = importlib.util.spec_from_file_location("cold_producer_v40_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V40 = _load(SCRIPT)


def _actual_current() -> Path:
    sidecar = json.loads(SIDECAR.read_text(encoding="utf-8"))
    return Path(sidecar["actual_current"]["path"])


def _write_header(path: Path, *, actual: str, relocated: str) -> None:
    value = {
        "schema": V40.SCHEMA_HEADER,
        "status": "LABEL_HEADER_READY_DEVELOPMENT",
        "current_catalog_sha256": relocated,
        "current_source_identity": {"sha256": actual, "exact_current_source": True},
        "binding_status": "RELOCATED_RUNTIME_CURRENT_VIEW_SOURCE_BOUND",
        "labels": {"identity_axis": "(Zone,Idp)", "mass_scope": "initial_fluid_source_cohort_global"},
        "qualification": dict(V40.UNKNOWN),
    }
    value["sha256"] = V40.canonical_sha(value)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def test_tiny_relocation_v15_header_and_fresh_proof_use_new_view_digest(tmp_path: Path) -> None:
    actual_path = _actual_current()
    overlay_path = tmp_path / "CURRENT336-relocated.json"
    overlay_result = V40.make_relocated_overlay(
        actual_current=actual_path,
        target_trajectory=tmp_path / "copied" / "trajectory.h5",
        output=overlay_path)
    manifest = Path(overlay_result["manifest"])
    assert overlay_result["actual_current_sha256"] == V40.ACTUAL_CURRENT_SHA
    assert overlay_result["overlay_sha256"] not in {V40.ACTUAL_CURRENT_SHA, V40.HISTORICAL_OVERLAY_SHA}

    relocated_v15 = tmp_path / "replay-v15-relocated.json"
    V40.rebind_replay_v15(replay_request=V15_REQUEST, manifest=manifest, output=relocated_v15)
    v15 = json.loads(relocated_v15.read_text(encoding="utf-8"))
    assert v15["current_binding"]["sha256"] == overlay_result["overlay_sha256"]
    assert v15["current_binding"]["binding_status"] == "RELOCATED_RUNTIME_CURRENT_VIEW"
    assert v15["observer_profile"]["current_binding_sha256"] == overlay_result["overlay_sha256"]
    assert v15["current_binding"]["sha256"] != V40.HISTORICAL_OVERLAY_SHA

    contract_path = tmp_path / "source-contract-v40.json"
    V40.build_contract(v39_contract=V39_CONTRACT, relocated_v15=relocated_v15,
                       manifest=manifest, output=contract_path)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    assert contract["expected"]["source_binding"]["current_catalog_sha256"] == overlay_result["overlay_sha256"]
    assert contract["current_catalog_provenance"]["actual_current_catalog"]["sha256"] == V40.ACTUAL_CURRENT_SHA
    assert contract["current_catalog_provenance"]["relocated_runtime_view"]["sha256"] == overlay_result["overlay_sha256"]
    assert contract["v40_forward"]["v15_reader_consumes_new_view_digest"] is True
    assert contract["v40_forward"]["v39_builder_only_contract"] is True

    header = tmp_path / "label-header.json"
    _write_header(header, actual=V40.ACTUAL_CURRENT_SHA, relocated=overlay_result["overlay_sha256"])
    proof_path = tmp_path / "fresh-proof.json"
    result = V40.build_fresh_proof(source_contract=contract_path, relocated_v15=relocated_v15,
                                   label_header=header, output=proof_path)
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    assert result["payload_read"] is False
    assert proof["source_binding"]["current_catalog_sha256"] == overlay_result["overlay_sha256"]
    assert proof["source_binding"]["current_source_identity_sha256"] == V40.ACTUAL_CURRENT_SHA
    assert proof["fresh_proof_scope"]["historical_v39_overlay_sha256_not_used_as_runtime_input"] is True


def test_fresh_proof_rejects_old_historical_digest(tmp_path: Path) -> None:
    overlay_result = V40.make_relocated_overlay(
        actual_current=_actual_current(), target_trajectory=tmp_path / "copied" / "trajectory.h5",
        output=tmp_path / "CURRENT336-relocated.json")
    manifest = Path(overlay_result["manifest"])
    relocated_v15 = tmp_path / "replay-v15-relocated.json"
    V40.rebind_replay_v15(replay_request=V15_REQUEST, manifest=manifest, output=relocated_v15)
    contract_path = tmp_path / "source-contract-v40.json"
    V40.build_contract(v39_contract=V39_CONTRACT, relocated_v15=relocated_v15,
                       manifest=manifest, output=contract_path)
    header = tmp_path / "bad-header.json"
    _write_header(header, actual=V40.ACTUAL_CURRENT_SHA, relocated=V40.HISTORICAL_OVERLAY_SHA)
    with pytest.raises(V40.ColdProducerV40Error, match="new relocated view digest"):
        V40.build_fresh_proof(source_contract=contract_path, relocated_v15=relocated_v15,
                              label_header=header, output=tmp_path / "proof.json")
