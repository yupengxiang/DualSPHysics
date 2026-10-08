from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_fresh_v16_proof_consumer_v8.py"


def _load():
    spec = importlib.util.spec_from_file_location("fresh_v16_proof_v8_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v8 = _load()


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path, dict, dict]:
    relocated = tmp_path / "relocated"
    output_root = relocated / "output"
    target_root = relocated / "target"
    output_root.mkdir(parents=True)
    target_root.mkdir(parents=True)
    original = tmp_path / "original-source"
    original.mkdir()
    result_path = output_root / "v16-result.json"
    pairs = [(0, index) for index in range(1, 6)]
    statuses = ["observed", "right_censored", "failed_before_observation",
                "initially_inside", "ambiguous_multiple_crossing"]
    labels = []
    receivers = []
    for index, ((zone, idp), status) in enumerate(zip(pairs, statuses)):
        label = {
            "zone": zone, "idp": idp, "initial_mk": 1,
            "initial_mass_kg": 1.0, "status": status,
            "event_time_s": 1.5 if status == "observed" else None,
            "first_saved_bracket_s": ([1.0, 2.0] if status == "observed" else
                                       [2.0, 3.0] if status == "ambiguous_multiple_crossing" else None),
            "crossing_candidate_times_s": ([1.5] if status == "observed" else
                                            [2.2, 2.4] if status == "ambiguous_multiple_crossing" else []),
            "recross_status": "ENDPOINT_SAMPLE_ONLY_UNKNOWN_HIDDEN_RECROSSINGS",
            "velocity_status": ("WORLD_INERTIAL_NORMAL_SPEED_OBSERVED" if status == "observed"
                                 else "NOT_REQUIRED_FOR_POSITION_EVENT"),
            "relative_normal_speed_m_s": 0.5 if status == "observed" else None,
        }
        receiver = {
            "zone": zone, "idp": idp, "status": status,
            "event_time_s": label["event_time_s"],
            "first_saved_bracket_s": label["first_saved_bracket_s"],
            "final_destination_status": ("inside_receiver_volume" if index == 0 else
                                          "outside_receiver_volume" if index < 4 else
                                          "unknown_final_destination"),
            "aperture_first_arrival_status": "NO_CANDIDATE",
        }
        labels.append(label)
        receivers.append(receiver)
    counts = {status: 1 for status in statuses}
    identity_sha = v8._identity_sha(labels)
    source_files = {"current_catalog": _sha("current"), "generated_xml": _sha("xml"),
                    "motion_dat": _sha("motion"), "scientific_scan_sidecar": _sha("scan")}
    source_binding = {
        "binding_status": "EXACT_CURRENT_SOURCE_BOUND",
        "current_catalog_sha256": source_files["current_catalog"],
        "trajectory_h5_producer_sha256": _sha("h5"),
        "source_files": source_files,
    }
    profile = {
        "schema": "ds02.stage2.f2-s1-observer-profile.v14",
        "sha256": _sha("profile"), "query_times_s": [0.0, 1.0, 2.0, 3.0],
        "observable_names": ["mass_weighted_com_m", "mass_weighted_mean_velocity_m_s",
                              "mass_weighted_kinetic_energy_J", "mass_quantile_front_m",
                              "event_status"],
    }
    result = {
        "schema": v8.RESULT_SCHEMA, "model_invoked": False, "cfd_invoked": False,
        "case_identity": {"family_id": "F2", "physical_case_id": "F2_PHYSICAL",
                           "runtime_case_alias": "F2_RUNTIME"},
        "source_binding": source_binding,
        "cohort": {"selected_count": 5, "identity_key": "(Zone,Idp)",
                   "selected_identity_sha256": identity_sha},
        "initial_mass_denominator": {
            "selected_initial_mass_kg": 5.0, "initial_fluid_mass_kg": 5.0,
            "denominator_kg": 5.0, "initial_missing_mass_kg": 0.0,
            "later_missing_unique_count": 1, "later_missing_mass_kg": 0.2,
            "missing_scope": "later missing mass remains outside the initial denominator",
        },
        "window": {"frame_start": 0, "frame_stop": 3, "frame_count": 4,
                   "time_start_s": 0.0, "time_stop_s": 3.0},
        "velocity_semantics": "world_inertial_m_per_s; body-frame position does not imply relative velocity",
        "observer_profile": profile,
        "frame_observations": [
            {"time_s": float(index), "quality": dict(v8.UNKNOWN),
             "mass_weighted_com_m": [0.0, 0.0, 0.0],
             "mass_weighted_mean_velocity_m_s": [0.0, 0.0, 0.0],
             "mass_weighted_kinetic_energy_J": 0.0,
             "mass_quantile_front_m": [0.0, 0.0, 0.0, 0.0]}
            for index in range(4)
        ],
        "labels": labels, "receiver_volume_labels": receivers,
        "event_summary": {
            "label_counts": counts, "receiver_volume_label_counts": counts,
            "net_flux_known_endpoint_subtotal_kg": 1.0,
            "net_flux_unknown_endpoint_contribution_interval_kg": [0.0, 0.2],
            "net_flux_total_interval_kg": [1.0, 1.2],
            "gross_flux_mass_kg": None,
            "gross_flux_status": "UNKNOWN_HIDDEN_WITHIN_SAVED_BRACKET_RECROSSINGS",
            "residence_known_mass_time_kg_s": 1.0,
            "residence_output_mode": "per_particle_compact; no global identity-free interval list",
            "residence_unknown_mass_time_semantics": "upper bound for unknown intervals",
        },
        "quality": dict(v8.UNKNOWN),
    }
    result_path.write_text(json.dumps(result, sort_keys=True, allow_nan=False))
    result_sha = v8.sha256_file(result_path)[0]
    request = {
        "schema": v8.REQUEST_SCHEMA, "role": "DEVELOPMENT",
        "status": "READY_FOR_PARENT_GUARD", "model_invoked": False,
        "cfd_invoked": False, "ledger_mutated": False, "quality": dict(v8.UNKNOWN),
        "result": {"path": str(result_path), "sha256": result_sha,
                   "bytes": result_path.stat().st_size},
        "relocation": {"target_root": str(target_root), "output_root": str(output_root),
                       "original_roots": [str(original)]},
        "expected": {
            "source_binding": source_binding,
            "case_identity": result["case_identity"],
            "cohort": {"selected_count": 5, "identity_key": "(Zone,Idp)",
                       "identity_sha256": identity_sha},
            "initial_mass_denominator": {"denominator_kg": 5.0,
                                          "initial_missing_mass_kg": 0.0,
                                          "later_missing_unique_count": 1,
                                          "later_missing_mass_kg": 0.2,
                                          "tolerance_kg": 1e-9},
            "time": {"frame_count": 4, "first_s": 0.0, "last_s": 3.0,
                     "tolerance_s": 1e-12,
                     "observer_profile_sha256": profile["sha256"]},
            "events": {"status_vocabulary": sorted(v8.FIRST_PASSAGE_STATUSES),
                       "require_unknown_recross": True,
                       "require_total_net_interval": True,
                       "require_receiver_labels": True,
                       "require_residence_semantics": True},
            "observer_fields": ["mass_weighted_com_m", "mass_weighted_mean_velocity_m_s",
                                "mass_weighted_kinetic_energy_J", "mass_quantile_front_m"],
        },
        "execution": {"max_wall_seconds": 30.0,
                       "max_result_bytes": 2_000_000,
                       "read_hdf5_or_bi4": False, "raw_opened": False},
    }
    request["sha256"] = v8.canonical_sha(request)
    request_path = tmp_path / "proof-request.json"
    request_path.write_text(json.dumps(request, sort_keys=True, allow_nan=False))
    return request_path, result_path, request, result


def test_preflight_is_metadata_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    request_path, _, _, _ = _fixture(tmp_path)
    monkeypatch.setattr(v8, "_read_result", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("result read")))
    value = v8.preflight(request_path)
    assert value["status"] == "READY_FOR_PARENT_IO_SLOT"
    assert value["result"]["content_sha_verified"] is False
    assert value["hdf5_or_bi4_content_read"] is False


def test_guarded_run_reads_only_relocated_json_and_writes_small_proof(tmp_path: Path) -> None:
    request_path, result_path, _, _ = _fixture(tmp_path)
    output = request_path.parent / "relocated" / "output" / "fresh-proof-v8.json"
    command = [sys.executable, str(SCRIPT), "run", "--request", str(request_path),
               "--output", str(output), "--io-slot-approved",
               "--parent-pid", str(os.getpid()), "--max-wall-seconds", "30"]
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    assert completed.returncode == 0, completed.stderr
    proof = json.loads(output.read_text())
    assert proof["status"] == "FRESH_V16_RESULT_VERIFIED_DEVELOPMENT_UNKNOWN"
    assert proof["source_result"]["sha256"] == v8.sha256_file(result_path)[0]
    assert proof["execution"]["json_only"] is True
    assert proof["execution"]["hdf5_or_bi4_content_read"] is False
    assert proof["qualification"] == v8.UNKNOWN
    assert proof["event_censor"]["label_status_counts"]["ambiguous_multiple_crossing"] == 1
    assert proof["initial_mass_denominator"]["denominator_unchanged_by_later_missing"] is True
    assert proof["sha256"] == v8.canonical_sha(proof)


@pytest.mark.parametrize("mutation", ["identity", "mass", "wrong_time", "nan_speed", "legacy_flux"])
def test_semantic_mutations_are_rejected(tmp_path: Path, mutation: str) -> None:
    request_path, result_path, request, result = _fixture(tmp_path)
    bound = v8._validate_request(request, verify_result_stat=True)
    bad = copy.deepcopy(result)
    if mutation == "identity":
        bad["labels"][0]["idp"] = 99
    elif mutation == "mass":
        bad["labels"][0]["initial_mass_kg"] = 2.0
    elif mutation == "wrong_time":
        bad["window"]["time_stop_s"] = 2.0
    elif mutation == "nan_speed":
        bad["labels"][0]["relative_normal_speed_m_s"] = float("nan")
    elif mutation == "legacy_flux":
        bad["event_summary"]["net_flux_interval_kg"] = [0.0, 1.0]
    result_path.write_text(json.dumps(bad, sort_keys=True, allow_nan=True))
    observed_sha, observed_bytes = v8.sha256_file(result_path)
    with pytest.raises(v8.ProofConsumerError):
        v8._validate_result(bad, bound, observed_sha, observed_bytes)


def test_original_actionable_path_and_old_proof_are_not_accepted(tmp_path: Path) -> None:
    request_path, result_path, request, result = _fixture(tmp_path)
    bound = v8._validate_request(request, verify_result_stat=True)
    result["execution"] = {"path": str(request["relocation"]["original_roots"][0] + "/raw.h5")}
    result_path.write_text(json.dumps(result, sort_keys=True, allow_nan=False))
    paths = v8._path_audit(
        result, original_roots=bound["original_roots"], allowed_roots=bound["roots"])
    assert paths["actionable_original_path_hits"]
    assert not (tmp_path / "relocated" / "output" / "bad-proof.json").exists()
