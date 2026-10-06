#!/usr/bin/env python3
"""Metadata-only validation for the F3 fresh107 source handoff.

The validator reads only package JSON and Python source.  It never opens,
reads, copies, or hashes BI4/H5/CSV/DAT/VTK/scientific solver output.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
PITCHES = (0.9, 1.1)
AYS = (0.29, 0.36, 0.43, 0.50, 0.54, 0.57, 0.64, 0.70)
EXPECTED = [
    (pitch, ay, f"F3_STAGE1_DP006_P{round(pitch * 1000):04d}_AY{round(ay * 1000):04d}")
    for pitch in PITCHES for ay in AYS
]
SCIENCE_SUFFIXES = {".bi4", ".h5", ".hdf5", ".csv", ".dat", ".vtk", ".npy", ".npz"}


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    if path.suffix.lower() in SCIENCE_SUFFIXES:
        raise AssertionError(f"scientific payload hash attempted: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_null_future(value, key_path: str = "") -> None:
    """Reject non-null values only for future/output hash and receipt fields."""
    if isinstance(value, dict):
        for key, child in value.items():
            lower = key.lower()
            full = f"{key_path}.{key}" if key_path else key
            future = (
                lower in {
                    "actual_forcing_sha256", "future_forcing_sha256",
                    "future_physical_condition_sha256", "physical_condition_sha256",
                    "future_gencase_receipt", "future_prepared_input_report",
                    "future_generated_xml_sha256", "future_generated_bi4_sha256",
                    "future_dat_sha256", "future_native_receipt", "future_typed_receipt",
                    "future_h5_sha256", "future_visual_decision", "future_execution_receipt",
                    "future_report_sha256", "future_xml_sha256", "future_bi4_sha256",
                    "future_forcing_sha256", "future_condition_sha256",
                }
                or lower.endswith("_receipt") and lower.startswith("future_")
            )
            if future and child is not None:
                raise AssertionError(f"future artifact is materialized at {full}: {child!r}")
            assert_null_future(child, full)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_null_future(child, f"{key_path}[{index}]")


def main() -> int:
    manifest = load(HERE / "manifest.json")
    assert manifest["fresh_id"] == "fresh107"
    assert manifest["family_id"] == "F3"
    assert manifest["candidate_count"] == 16
    assert manifest["source_only"] is True
    assert manifest["execution_allowed"] is False
    assert manifest["launch_allowed"] is False
    assert manifest["production_scope_approval"] is False
    assert manifest["q_n"] == "not_granted"
    assert manifest["numerical_precision_status"] == "not_accepted"
    assert manifest["independent_case_count_increment"] == 0
    assert manifest["candidate_pitch_multipliers"] == list(PITCHES)
    assert manifest["candidate_ay_values_m_s2"] == list(AYS)

    binding = load(HERE / "source-binding.json")
    assert binding["scope_id"] == manifest["scope_id"]
    assert binding["candidate_count"] == 16
    actual_pairs = []
    for row, (pitch, ay, cid) in zip(binding["candidates"], EXPECTED):
        assert row["case_id"] == cid
        assert row["physical_case_id"] == f"F3_TWOAXIS_P{round(pitch * 1000):04d}_AY{round(ay * 1000):04d}_STAGE1_FIRST48_PITCH_VARIANT"
        assert float(row["nominal_pitch_multiplier"]) == pitch
        assert float(row["transverse_amplitude_m_s2"]) == ay
        assert row["launch_allowed"] is False
        actual_pairs.append((float(row["nominal_pitch_multiplier"]), float(row["transverse_amplitude_m_s2"])))
    assert actual_pairs == [(p, a) for p in PITCHES for a in AYS]
    assert binding["initialization_contract"] == {
        "genuine_parent": "Gen056 plus QA058 and Root704/705 exact-initial review",
        "dimension": 3,
        "definition_dp_m": 0.006,
        "nominal_pitch_recipe_unchanged": True,
        "tmax_s": 8.35,
        "tout_s": 0.01,
        "expected_saved_frames": 836,
        "solver_mode": "-mdbc_noslip:1",
        "geometry_unchanged": True,
        "initial_particle_reference": {"total": 179208, "fluid": 67500, "fixed": 111708, "moving": 0},
        "future_actual_particle_counts": None,
    }
    assert binding["source_builder_policy"]["transformer_pitch_argument"] == "amplitude_x"
    assert binding["source_builder_policy"]["transformer_transverse_argument"] == "amplitude_y"
    assert binding["source_builder_policy"]["solver_invocation"] is False
    assert binding["source_builder_policy"]["gencase_invocation_by_this_package"] is False
    assert binding["released_visual_domain_reference"]["nominal_pitch_multiplier_range"] == [0.8, 1.2]
    assert binding["released_visual_domain_reference"]["transverse_amplitude_range_m_s2"] == [0.25, 0.75]

    # Source code is inspected as text only; no module is imported and no worker runs.
    builder = (HERE / "source/source_builder.py").read_text(encoding="utf-8")
    assert "EXPECTED_PITCHES = (0.9, 1.1)" in builder
    assert "EXPECTED_AYS = (0.29, 0.36, 0.43, 0.50, 0.54, 0.57, 0.64, 0.70)" in builder
    assert "fresh107-prepared-index" in builder
    assert (HERE / "source/prepare_pitch_axis.py").is_file()

    batch_path = HERE / "requests/batch-source-preparation-request.json"
    batch = load(batch_path)
    assert batch["fresh_id"] == "fresh107"
    assert batch["disabled"] is True
    assert batch["launch"] is False
    assert batch["launch_allowed"] is False
    assert batch["execution_allowed"] is False
    assert batch["source_only"] is True
    assert batch["cpu_task_kind"] == "audit"
    assert batch["command"][1] == str(HERE / "source/source_builder.py")
    assert batch["command"][3] == str(HERE / "source-binding.json")
    assert set(batch["input_files"]) == set(batch["input_sha256"])
    batch_sha = sha(batch_path)

    for pitch, ay, cid in EXPECTED:
        condition_path = HERE / "conditions" / f"{cid}.json"
        owner_path = HERE / "owners" / f"{cid}.json"
        registration_path = HERE / "requests/input-preparation" / f"{cid}-input-preparation-registration.json"
        condition = load(condition_path)
        owner = load(owner_path)
        registration = load(registration_path)
        assert condition["case_id"] == cid
        assert condition["parameter_tuple"]["nominal_pitch_multiplier"] == pitch
        assert condition["parameter_tuple"]["transverse_amplitude_m_s2"] == ay
        assert condition["parameter_tuple"]["definition_dp_m"] == 0.006
        assert condition["parameter_tuple"]["time_max_s"] == 8.35
        assert condition["parameter_tuple"]["save_interval_s"] == 0.01
        assert condition["parameter_tuple"]["dimension"] == 3
        assert owner["case_id"] == cid
        assert owner["nominal_pitch_multiplier"] == pitch
        assert owner["transverse_amplitude_m_s2"] == ay
        assert owner["shared_initial_state_reference"]["reference_native_particles"] == 179208
        assert owner["shared_initial_state_reference"]["reference_native_fluid"] == 67500
        assert owner["shared_initial_state_reference"]["reference_native_fixed"] == 111708
        assert owner["shared_initial_state_reference"]["reference_actual_3d"] is True
        assert owner["production_gate"]["launch_allowed"] is False
        assert owner["production_gate"]["execution_allowed"] is False
        assert registration["batch_request"]["sha256"] == batch_sha
        assert registration["disabled"] is True
        assert registration["launch_allowed"] is False
        assert registration["execution_allowed"] is False
        assert registration["output_contract"]["future_bi4_sha256"] is None
        assert registration["output_contract"]["future_forcing_sha256"] is None
        assert registration["output_contract"]["future_execution_receipt"] is None
        assert registration["recipe_contract"] == {"definition_dp_m": 0.006, "tmax_s": 8.35, "tout_s": 0.01, "expected_saved_frames": 836, "solver_mode": "-mdbc_noslip:1"}
        runtime = registration["runtime_registration"]
        assert runtime["launch_owner"] == "root"
        assert runtime["cpu_threads"] == 4
        assert runtime["command_inherited_from_batch"] is True
        assert runtime["no_direct_launch_by_source_agent"] is True
        assert_null_future(condition)
        assert_null_future(owner)
        assert_null_future(registration)

    visual = load(HERE / "requests/stage1-visual-authorizer-batch-request.json")
    assert visual["new_case_ids"] == [cid for _, _, cid in EXPECTED]
    assert visual["production_selected_case_ids"] == []
    assert visual["execution_allowed"] is False
    assert all(item["sha256"] == sha(Path(item["path"])) for item in visual["request_paths"])
    dup = load(HERE / "metadata/duplicate-check.json")
    assert dup["case_id_intersection"] == []
    assert dup["physical_tuple_intersection"] == []
    assert dup["p0900_existing_in_f3_source"] is False
    assert dup["p1100_existing_in_f3_source"] is False

    # Validate package-local hash closure without touching any external or science file.
    for raw, digest in batch["input_sha256"].items():
        path = Path(raw)
        if str(path).startswith(str(HERE)):
            assert path.is_file(), path
            assert path.suffix.lower() not in SCIENCE_SUFFIXES
            assert sha(path) == digest, f"stale package input digest: {path}"

    print(json.dumps({"status": "PASS", "fresh_id": "fresh107", "candidate_count": 16, "science_payloads_opened": 0, "science_payloads_hashed": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
