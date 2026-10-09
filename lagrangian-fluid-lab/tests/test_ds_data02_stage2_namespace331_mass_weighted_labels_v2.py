"""Strict namespace331-v2 identity, region and role-bound tests."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_namespace331_mass_weighted_labels_v2.py"


def _load():
    spec = importlib.util.spec_from_file_location("namespace331_v2", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


N331 = _load()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _document(tmp_path: Path, *, identity_status: str = "CANONICAL") -> dict:
    tmp_path.mkdir(parents=True, exist_ok=True)
    bindings = []
    for role, semantic in (("source-proof", "source"),
                           ("owner-proof", "region_owner"),
                           ("control-proof", "control")):
        path = tmp_path / f"{role}.json"
        path.write_text(json.dumps({"role": semantic, "proof": "verified"}), encoding="utf-8")
        digest = _sha(path)
        bindings.append({"role": role, "semantic_role": semantic, "path": str(path),
                         "sha256": digest, "observed_sha256": digest,
                         "content_verified": True,
                         "content_policy": "SMALL_METADATA_PROOF_ONLY"})
    return {
        "schema": N331.EVENT_SCHEMA,
        "case_identity": {"family_id": "F1", "physical_case_id": "F1_V2_PAIR",
                           "identity_status": identity_status},
        "source_bindings": bindings,
        "observation_contract": {
            "source_status": "KNOWN", "region_owner_status": "KNOWN", "control_status": "KNOWN",
            "role_bindings": {"source": "source-proof", "region_owner": "owner-proof",
                              "control": "control-proof"},
            "source_region": "initial_fluid", "target_region": "receiver",
            "observation_window_s": [0.0, 4.0], "eligible_initial_mass_kg": 3.0,
        },
        "particles": [
            {"particle_identity": {"Zone": 0, "Idp": 1}, "particle_id": "Zone=0;Idp=1",
             "mass_kg": 2.0, "initial_region": "initial_fluid", "observation_status": "OBSERVED",
             "events": [
                 {"event_id": "p1-in", "event_type": "CROSSING", "time_s": 0.5,
                  "direction": "IN", "region": "receiver"},
                 {"event_id": "p1-stay", "event_type": "RESIDENCE_INTERVAL",
                  "start_time_s": 0.5, "end_time_s": 1.5, "region": "receiver"},
                 {"event_id": "p1-arrival", "event_type": "ARRIVAL", "time_s": 1.0,
                  "region": "receiver"},
                 {"event_id": "p1-out", "event_type": "CROSSING", "time_s": 1.5,
                  "direction": "OUT", "region": "receiver"},
             ]},
            {"particle_identity": {"Zone": 0, "Idp": 2}, "particle_id": "Zone=0;Idp=2",
             "mass_kg": 1.0, "initial_region": "initial_fluid", "observation_status": "CENSORED",
             "events": []},
            {"particle_identity": {"Zone": 1, "Idp": 1}, "particle_id": "Zone=1;Idp=1",
             "mass_kg": 3.0, "initial_region": "outside_cohort", "observation_status": "EXCLUDED",
             "events": []},
        ],
    }


def test_v2_requires_tuple_identity_and_filters_metrics_to_target_region(tmp_path: Path) -> None:
    document = _document(tmp_path)
    result = N331.produce_labels_v2(document, verify_sources=True)
    assert result["schema"] == N331.RESULT_SCHEMA
    assert result["metrics"]["crossing_count"] == 2
    assert result["metrics"]["gross_crossing_mass_kg"] == pytest.approx(4.0)
    assert result["metrics"]["residence_mass_time_kg_s"] == pytest.approx(2.0)
    assert result["labels"][0]["particle_identity"] == {"Zone": 0, "Idp": 1}
    assert N331.validate_result_v2(result, document, verify_sources=True)["recomputed"] is True


def test_v2_rejects_wrong_region_instead_of_silently_aggregating(tmp_path: Path) -> None:
    document = _document(tmp_path)
    wrong = json.loads(json.dumps(document))
    wrong["particles"][0]["events"][0]["region"] = "other_region"
    with pytest.raises(N331.Namespace331V2Error, match="outside target_region"):
        N331.validate_event_stream_v2(wrong, verify_sources=True)


def test_v2_rejects_duplicate_zone_idp_even_when_particle_strings_differ(tmp_path: Path) -> None:
    document = _document(tmp_path)
    duplicate = json.loads(json.dumps(document))
    duplicate["particles"][1]["particle_identity"] = {"Zone": 0, "Idp": 1}
    duplicate["particles"][1]["particle_id"] = "different-string"
    with pytest.raises(N331.Namespace331V2Error, match="canonical for \(Zone, Idp\)"):
        N331.validate_event_stream_v2(duplicate)
    duplicate["particles"][1]["particle_id"] = "Zone=0;Idp=1"
    with pytest.raises(N331.Namespace331V2Error, match="duplicate particle identity"):
        N331.validate_event_stream_v2(duplicate)


def test_v2_rejects_overlapping_or_duplicate_residence_intervals(tmp_path: Path) -> None:
    document = _document(tmp_path)
    overlap = json.loads(json.dumps(document))
    overlap["particles"][0]["events"] = [
        {"event_id": "r1", "event_type": "RESIDENCE_INTERVAL", "start_time_s": 0.5,
         "end_time_s": 2.0, "region": "receiver"},
        {"event_id": "r2", "event_type": "RESIDENCE_INTERVAL", "start_time_s": 1.5,
         "end_time_s": 3.0, "region": "receiver"},
    ]
    with pytest.raises(N331.Namespace331V2Error, match="overlapping residence"):
        N331.validate_event_stream_v2(overlap)


def test_v2_unknown_case_identity_returns_all_unknown(tmp_path: Path) -> None:
    document = _document(tmp_path, identity_status="UNKNOWN")
    result = N331.produce_labels_v2(document, verify_sources=True)
    assert result["derived_status"] == "UNKNOWN"
    assert all(row["label_status"] == "UNKNOWN_MISSING_CASE_IDENTITY_OR_BINDING"
               for row in result["labels"])
    assert all(value is None for value in result["metrics"].values())


def test_v2_known_role_requires_hash_bound_semantic_role_not_arbitrary_python(tmp_path: Path) -> None:
    document = _document(tmp_path)
    py_path = tmp_path / "not-a-source-proof.py"
    py_path.write_text("print('not a binding')\n", encoding="utf-8")
    digest = _sha(py_path)
    document["source_bindings"][1].update({"path": str(py_path), "sha256": digest,
                                           "observed_sha256": digest,
                                           "semantic_role": "region_owner"})
    with pytest.raises(N331.Namespace331V2Error, match="arbitrary Python file"):
        N331.produce_labels_v2(document, verify_sources=True)


def test_v2_known_role_rejects_unobserved_hash_and_request_is_v2(tmp_path: Path) -> None:
    document = _document(tmp_path)
    document["source_bindings"][2].pop("observed_sha256")
    document["source_bindings"][2]["content_verified"] = False
    with pytest.raises(N331.Namespace331V2Error, match="hash-bound observed SHA"):
        N331.validate_event_stream_v2(document)
    valid = _document(tmp_path / "valid")
    events = tmp_path / "valid-events.json"
    events.write_text(json.dumps(valid), encoding="utf-8")
    request = N331.build_request_v2(
        events, tmp_path / "result.json", source_bindings=valid["source_bindings"],
        family_id="F1", physical_case_id="F1_V2_PAIR")
    assert request["schema"] == N331.REQUEST_SCHEMA
    assert request["request_sha256"] == N331.canonical_sha(request)
    assert request["binding_requirements"]["known_requires_observed_sha256"] is True
