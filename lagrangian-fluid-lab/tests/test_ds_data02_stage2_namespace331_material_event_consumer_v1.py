from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_namespace331_material_event_consumer_v1.py"
SPEC = importlib.util.spec_from_file_location("material_event_consumer_v1_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path, *, alias: bool = False) -> tuple[Path, Path, dict]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    source_bindings = []
    for role, semantic in (("source-proof", "source"),
                           ("owner-proof", "region_owner"),
                           ("control-proof", "control")):
        path = tmp_path / f"{role}.json"
        path.write_text(json.dumps({"role": semantic, "proof": "fixture-only"}))
        digest = _sha(path)
        source_bindings.append({"role": role, "semantic_role": semantic, "path": str(path),
                                "sha256": digest, "observed_sha256": digest,
                                "content_verified": True, "hash_verified_after_reservation": True,
                                "content_policy": "SMALL_METADATA_FIXTURE_ONLY"})
    case = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090" if alias else "F1_FIXTURE_CASE"
    event = {
        "schema": MODULE._EVENT.EVENT_SCHEMA,
        "case_identity": {"family_id": "F1", "physical_case_id": case,
                           "identity_status": "CANONICAL"},
        "source_bindings": source_bindings,
        "observation_contract": {
            "source_status": "UNKNOWN", "region_owner_status": "UNKNOWN", "control_status": "UNKNOWN",
            "role_bindings": {}, "source_region": "initial_fluid", "target_region": "receiver",
            "observation_window_s": [0.0, 1.0], "eligible_initial_mass_kg": 1.0,
        },
        "particles": [{"particle_identity": {"Zone": 0, "Idp": 1},
                        "particle_id": "Zone=0;Idp=1", "mass_kg": 1.0,
                        "initial_region": "initial_fluid", "observation_status": "CENSORED",
                        "events": []}],
    }
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event))
    current = {"schema": "ds02.stage2.fixture.current336.v1",
               "cases": [{"physical_case_id": case}]}
    current_path = tmp_path / "current.json"
    current_path.write_text(json.dumps(current))
    return event_path, current_path, {"event": event, "sources": source_bindings,
                                     "case": case}


def test_real_v2_validator_chain_returns_unknown_without_role_credit(tmp_path: Path) -> None:
    event_path, current_path, info = _fixture(tmp_path)
    request_path = tmp_path / "request.json"
    request = MODULE.build_request(
        event_path, tmp_path / "result.json",
        current_binding={"path": str(current_path), "sha256": _sha(current_path),
                         "case_index": 0, "physical_case_id": info["case"]},
        source_bindings=info["sources"], allow_fixture=True,
    )
    request_path.write_text(json.dumps(request))
    result = MODULE.run_request(request_path, allow_fixture=True)
    assert result["schema"] == MODULE.RESULT_SCHEMA
    assert result["derived_status"] == "UNKNOWN"
    assert result["censoring"]["status"] == "UNKNOWN_ROLE_CLOSURE"
    assert all(value is None for value in result["censoring"]["metrics"].values())
    assert result["production_eligible"] is False
    assert result["qualification"] == MODULE.UNKNOWN_QUALIFICATION


def test_historical_f2_alias_is_rejected_by_current_gate(tmp_path: Path) -> None:
    event_path, current_path, info = _fixture(tmp_path, alias=True)
    with pytest.raises(MODULE.MaterialEventConsumerError, match="historical F2 alias"):
        MODULE.build_request(
            event_path, tmp_path / "result.json",
            current_binding={"path": str(current_path), "sha256": _sha(current_path),
                             "case_index": 0, "physical_case_id": info["case"]},
            source_bindings=info["sources"], allow_fixture=True,
        )


def test_changed_event_stream_sha_is_rejected_before_consume(tmp_path: Path) -> None:
    event_path, current_path, info = _fixture(tmp_path)
    request = MODULE.build_request(
        event_path, tmp_path / "result.json",
        current_binding={"path": str(current_path), "sha256": _sha(current_path),
                         "case_index": 0, "physical_case_id": info["case"]},
        source_bindings=info["sources"], allow_fixture=True,
    )
    request["event_stream"]["sha256"] = "0" * 64
    request["request_sha256"] = MODULE._EVENT.canonical_sha(request)
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request))
    with pytest.raises(MODULE.MaterialEventConsumerError, match="event stream SHA"):
        MODULE.run_request(path, allow_fixture=True)

