#!/usr/bin/env python3
"""Static, source-only validation for the fresh065 handoff.

This test intentionally never opens or hashes BI4, H5, or CSV payloads.  It
checks the generated JSON contract, small source-file hash closures, exact
candidate axes, and disabled execution gates.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
ARRAY_SUFFIXES = {".bi4", ".csv", ".h5", ".hdf5", ".npy", ".npz"}
PITCHES = (0.8, 1.2)
AYS = (0.25, 0.29, 0.32, 0.36, 0.39, 0.43, 0.46, 0.50, 0.54, 0.57, 0.64, 0.75)
EXPECTED_PAIRS = tuple((pitch, ay) for pitch in PITCHES for ay in AYS)
BASELINE_XML_SHA = "1162322010c42b9a084d76db0e20de571111cb009eb3afb699f2ee4c17d37406"
BASELINE_BI4_SHA = "c9c3fb8315dad402f77dd015539be376c3df68f332f3ed6d03e6c174e4c57d80"


def load(relative: str) -> dict:
    return json.loads((HERE / relative).read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def check_hash_closure(request: dict) -> None:
    files = request["input_files"]
    hashes = request["input_sha256"]
    assert set(files) == set(hashes), "input file/hash closure is incomplete"
    for raw in files:
        path = Path(raw)
        assert path.is_file(), f"missing source input: {path}"
        if path.suffix.lower() in ARRAY_SUFFIXES:
            # Known baseline array hashes are carried metadata.  The source
            # check must not read these payloads.
            assert hashes[raw] in {BASELINE_BI4_SHA}, f"unexpected array hash: {path}"
        else:
            assert digest(path) == hashes[raw], f"source hash mismatch: {path}"


def main() -> int:
    binding = load("source-binding.json")
    helper = load("helper-binding.json")
    manifest = load("first48-manifest.json")
    batch = load("requests/batch-source-preparation-request.json")
    visual = load("requests/stage1-visual-authorizer-batch-request.json")

    assert binding["fresh_id"] == helper["fresh_id"] == manifest["fresh_id"] == "fresh065"
    assert manifest["scope_id"] == binding["scope_id"] == helper["scope_id"]
    assert manifest["case_count"] == 48 and manifest["new_case_count"] == 24
    assert manifest["first24_exact_subset"]["case_count"] == 24
    assert manifest["first24_exact_subset"]["rows_unchanged"] is True
    assert len(manifest["first48_case_ids"]) == 48
    assert manifest["first48_case_ids"][:24] == manifest["first24_exact_subset"]["case_ids"]

    candidates = binding["candidates"]
    pairs = tuple((float(row["nominal_pitch_multiplier"]), float(row["transverse_amplitude_m_s2"])) for row in candidates)
    assert pairs == EXPECTED_PAIRS
    assert len({row["case_id"] for row in candidates}) == 24
    assert len({row["physical_case_id"] for row in candidates}) == 24
    assert all(row["future_actual_forcing_sha256"] is None for row in candidates)
    assert all(row["future_physical_condition_sha256"] is None for row in candidates)
    assert binding["preparation_script"].endswith("/prepare_pitch_axis.py")
    assert binding["source_provenance"]["fresh065_pitch_axis_preparation"]["transformer_pitch_argument"] == "amplitude_x"
    assert helper["fresh065_pitch_axis_preparation"]["transformer_transverse_argument"] == "amplitude_y"
    initial = binding["baseline_initial_reference"]["initial_native_verified"]
    assert initial["actual_3d"] is True
    assert initial["native_particles"] == 179208
    assert initial["native_fluid"] == 67500
    assert initial["native_fixed"] == 111708

    expected_case_ids = {row["case_id"] for row in candidates}
    conditions = sorted((HERE / "conditions").glob("*.json"))
    owners = sorted((HERE / "owners").glob("*.json"))
    requests = sorted(
        path for path in (HERE / "requests").glob("F3_*.json")
        if path.name not in {"batch-source-preparation-request.json", "stage1-visual-authorizer-batch-request.json"}
    )
    assert {path.stem for path in conditions} == expected_case_ids
    assert {path.stem for path in owners} == expected_case_ids
    assert {path.stem for path in requests} == expected_case_ids

    for path in conditions:
        condition = json.loads(path.read_text(encoding="utf-8"))
        assert condition["status"] == "pending_actual_cpu_preparation"
        assert condition["actual_forcing_sha256"] is None
        assert condition["physical_condition_sha256"] is None
        assert condition["xml_sha256_expected"] == BASELINE_XML_SHA
        assert condition["bi4_sha256_expected"] == BASELINE_BI4_SHA
        assert condition["geometry_and_initial_state"].startswith("byte-identical clone")

    for path in owners:
        owner = json.loads(path.read_text(encoding="utf-8"))
        assert owner["status"] == "pending_actual_cpu_preparation"
        assert owner["production_gate"]["launch_allowed"] is False
        assert owner["production_gate"]["production_approval"] == "none"
        assert owner["production_gate"]["independent_case_count_increment"] == 0
        assert owner["source_preparation"]["actual_forcing_sha256"] is None
        assert owner["source_preparation"]["physical_condition_sha256"] is None
        assert digest(HERE / "canonical-physical-binding-template.json") == owner["canonical_physical_binding_template"]["sha256"]
        condition_path = Path(owner["condition_template"]["path"])
        assert condition_path.is_file()
        assert digest(condition_path) == owner["condition_template"]["sha256"]

    for path in requests:
        request = json.loads(path.read_text(encoding="utf-8"))
        assert request["case_id"] == path.stem
        owner_path = Path(request["source_owner"]["path"])
        assert owner_path.is_file()
        assert digest(owner_path) == request["source_owner"]["sha256"]
        assert request["launch_allowed"] is False and request["execution_allowed"] is False
        assert request["production_approval"] == "none"
        assert request["q_n"] == "not_granted"
        assert request["numerical_precision_status"] == "not_accepted"
        assert request["independent_case_count_increment"] == 0
        assert request["physical_condition_sha256"] is None
        assert request["prepared_input_gate"]["forcing_sha256"] is None
        assert request["prepared_input_gate"]["physical_condition_sha256"] is None
        assert request["expected_saved_frames"] == 836
        assert request["save_interval_s"] == 0.01
        assert request["complete_event_window_s"] == [0.0, 8.35]
        assert request["actual_solver_command"][1:] == [
            "-mdbc_noslip:1",
            request["actual_solver_command"][2],
            "{attempt_root}/solver_output",
            "-tmax:8.35",
            "-tout:0.01",
        ]
        check_hash_closure(request)

    check_hash_closure(batch)
    assert batch["launch_allowed"] is False and batch["execution_allowed"] is False
    assert batch["output_contract"]["future_forcing_hashes"] is None
    assert batch["output_contract"]["future_condition_hashes"] is None
    assert visual["execution_allowed"] is False
    assert visual["production_scope_approval"] is False
    assert visual["production_selected_case_ids"] == []
    assert visual["no_future_hashes_claimed"] is True
    assert len(visual["request_paths"]) == 24
    for entry in visual["request_paths"]:
        assert digest(Path(entry["path"])) == entry["sha256"]

    package_payloads = [path for path in HERE.rglob("*") if path.is_file() and path.suffix.lower() in ARRAY_SUFFIXES]
    assert not package_payloads, f"array-bearing payload unexpectedly copied into package: {package_payloads}"
    print("fresh065 static contract: PASS (24 new candidates, 48 manifest, all disabled, no array payloads read)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
