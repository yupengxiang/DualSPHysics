"""Tiny source-bound tests for namespace331 mass/event labels."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_namespace331_mass_weighted_labels.py"


def _load():
    spec = importlib.util.spec_from_file_location("namespace331", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


N331 = _load()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _document(tmp_path: Path, *, statuses: tuple[str, str, str] = ("KNOWN", "KNOWN", "KNOWN")) -> tuple[dict, Path]:
    proof = tmp_path / "proof.json"
    proof.write_text(json.dumps({"schema": "manufactured.source-proof.v1", "status": "metadata-only"}), encoding="utf-8")
    source = {
        "role": "frozen_small_proof",
        "path": str(proof),
        "sha256": _sha(proof),
        "content_policy": "SMALL_METADATA_PROOF_ONLY",
        "bytes": proof.stat().st_size,
    }
    document = {
        "schema": N331.EVENT_SCHEMA,
        "case_identity": {
            "family_id": "F1",
            "physical_case_id": "F1_MANUFACTURED_MATCHED_PAIR",
            "identity_status": "CANONICAL",
        },
        "source_bindings": [source],
        "observation_contract": {
            "source_status": statuses[0],
            "region_owner_status": statuses[1],
            "control_status": statuses[2],
            "source_region": "initial_fluid",
            "target_region": "receiver",
            "observation_window_s": [0.0, 4.0],
            "eligible_initial_mass_kg": 3.0,
        },
        "particles": [
            {
                "particle_id": "p1",
                "mass_kg": 2.0,
                "initial_region": "initial_fluid",
                "observation_status": "OBSERVED",
                "events": [
                    {"event_id": "p1-cross-in", "event_type": "CROSSING", "time_s": 0.5,
                     "direction": "IN", "region": "receiver"},
                    {"event_id": "p1-residence", "event_type": "RESIDENCE_INTERVAL",
                     "start_time_s": 0.5, "end_time_s": 1.5, "region": "receiver"},
                    {"event_id": "p1-arrival", "event_type": "ARRIVAL", "time_s": 1.0,
                     "region": "receiver"},
                    {"event_id": "p1-cross-out", "event_type": "CROSSING", "time_s": 1.5,
                     "direction": "OUT", "region": "receiver"},
                ],
            },
            {
                "particle_id": "p2",
                "mass_kg": 1.0,
                "initial_region": "initial_fluid",
                "observation_status": "CENSORED",
                "events": [
                    {"event_id": "p2-cross-in", "event_type": "CROSSING", "time_s": 0.75,
                     "direction": "IN", "region": "receiver"},
                ],
            },
            {
                "particle_id": "p3",
                "mass_kg": 3.0,
                "initial_region": "outside_cohort",
                "observation_status": "EXCLUDED",
                "events": [],
            },
        ],
    }
    return document, proof


def test_namespace331_mass_weighted_arrival_crossing_residence_and_buckets(tmp_path: Path) -> None:
    document, _ = _document(tmp_path)
    result = N331.produce_labels(document, verify_sources=True)
    assert result["derived_status"] == "OBSERVED_METADATA_ONLY_DEVELOPMENT_UNKNOWN"
    assert result["metrics"] == {
        "first_arrival_mass_weighted_time_s": 1.0,
        "first_arrival_mass_kg": 2.0,
        "first_arrival_count": 1,
        "right_censored_mass_kg": 1.0,
        "excluded_mass_kg": 3.0,
        "no_arrival_observed_mass_kg": 0.0,
        "crossing_count": 3,
        "gross_crossing_mass_kg": 5.0,
        "net_flux_mass_kg": 1.0,
        "net_flux_rate_kg_s": 0.25,
        "mass_weighted_residence_time_s": pytest.approx(2.0 / 3.0),
        "residence_mass_time_kg_s": 2.0,
    }
    assert [row["label_status"] for row in result["labels"]] == [
        "OBSERVED_FIRST_ARRIVAL", "RIGHT_CENSORED_NO_ARRIVAL", "EXCLUDED"
    ]
    assert result["mass_accounting"]["denominator_excludes_excluded"] is True
    assert result["qualification"] == N331.QUALIFICATION_UNKNOWN
    assert N331.validate_result(result, document, verify_sources=True)["status"].startswith("PASS_")


def test_namespace331_missing_source_owner_or_control_is_unknown(tmp_path: Path) -> None:
    document, _ = _document(tmp_path, statuses=("KNOWN", "UNKNOWN", "KNOWN"))
    result = N331.produce_labels(document, verify_sources=True)
    assert result["derived_status"] == "UNKNOWN"
    assert all(row["label_status"] == "UNKNOWN_MISSING_SOURCE_OWNER_OR_CONTROL"
               for row in result["labels"])
    assert all(value is None for value in result["metrics"].values())
    assert result["qualification"] == N331.QUALIFICATION_UNKNOWN


def test_namespace331_distinguishes_censoring_and_exclusion_and_rejects_bad_event(tmp_path: Path) -> None:
    document, _ = _document(tmp_path)
    bad = json.loads(json.dumps(document))
    bad["particles"][2]["events"] = [{"event_id": "bad", "event_type": "ARRIVAL",
                                       "time_s": 1.0, "region": "receiver"}]
    with pytest.raises(N331.Namespace331Error, match="excluded particle"):
        N331.validate_event_stream(bad)
    assert document["particles"][1]["observation_status"] == "CENSORED"
    assert document["particles"][2]["observation_status"] == "EXCLUDED"


def test_namespace331_rejects_source_hash_duplicate_and_alias_failures(tmp_path: Path) -> None:
    document, proof = _document(tmp_path)
    bad = json.loads(json.dumps(document))
    bad["source_bindings"][0]["sha256"] = "0" * 64
    with pytest.raises(N331.Namespace331Error, match="SHA mismatch"):
        N331.produce_labels(bad, verify_sources=True)

    duplicate = json.loads(json.dumps(document))
    duplicate["particles"].append(json.loads(json.dumps(duplicate["particles"][0])))
    with pytest.raises(N331.Namespace331Error, match="particle_id missing or duplicated"):
        N331.validate_event_stream(duplicate)

    alias = json.loads(json.dumps(document))
    alias["case_identity"]["identity_status"] = "HISTORICAL_ALIAS"
    with pytest.raises(N331.Namespace331Error, match="historical aliases"):
        N331.validate_event_stream(alias)
    assert proof.is_file()


def test_namespace331_request_and_cli_are_bounded_and_source_bound(tmp_path: Path) -> None:
    document, proof = _document(tmp_path)
    stream = tmp_path / "events.json"
    stream.write_text(json.dumps(document), encoding="utf-8")
    output = tmp_path / "labels.json"
    request_path = tmp_path / "request.json"
    request = N331.build_request(
        stream, output,
        source_bindings=[{"role": "frozen_small_proof", "path": str(proof),
                          "sha256": _sha(proof), "content_policy": "PARENT_GUARD_DEFERRED"}],
        family_id="F1", physical_case_id="F1_MANUFACTURED_MATCHED_PAIR")
    assert request["schema"] == N331.REQUEST_SCHEMA
    assert request["request_sha256"] == N331.canonical_sha(request)
    assert request["execution"]["source_read_phase"] == "after_atomic_parent_reservation"
    assert request["qualification_boundary"] == N331.QUALIFICATION_UNKNOWN

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "produce", "--input", str(stream), "--output", str(output),
         "--verify-sources"], check=True, capture_output=True, text=True)
    assert '"schema": "' + N331.RESULT_SCHEMA + '"' in completed.stdout
    result = json.loads(output.read_text())
    assert N331.validate_result(result, document, verify_sources=True)["recomputed"] is True

    completed_request = subprocess.run(
        [sys.executable, str(SCRIPT), "build-request", "--input", str(stream),
         "--output", str(output), "--request", str(request_path), "--family-id", "F1",
         "--physical-case-id", "F1_MANUFACTURED_MATCHED_PAIR", "--source-binding",
         "frozen_small_proof", str(proof), _sha(proof)],
        check=True, capture_output=True, text=True)
    assert request_path.is_file()
    assert "request_sha256" in completed_request.stdout


def test_namespace331_result_validator_rejects_tampered_metrics(tmp_path: Path) -> None:
    document, _ = _document(tmp_path)
    result = N331.produce_labels(document)
    result["metrics"]["net_flux_mass_kg"] = 99.0
    with pytest.raises(N331.Namespace331Error, match="metrics"):
        N331.validate_result(result, document)

