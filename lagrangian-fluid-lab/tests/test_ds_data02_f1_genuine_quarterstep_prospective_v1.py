from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import h5py
import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HANDOFF_DIR = (
    REPO_ROOT
    / "campaigns"
    / "ds-data-02"
    / "families"
    / "F1"
    / "handoff_20261003"
    / "genuine_quarterstep_prospective_v1"
)

# Dynamically import transformer
TRANSFORMER_PATH = HANDOFF_DIR / "clone_transformer.py"
spec_trans = importlib.util.spec_from_file_location("clone_transformer", TRANSFORMER_PATH)
assert spec_trans and spec_trans.loader
clone_transformer = importlib.util.module_from_spec(spec_trans)
spec_trans.loader.exec_module(clone_transformer)

# Dynamically import label comparison
COMPARISON_PATH = HANDOFF_DIR / "f1_nominal_vs_half_native_labels_comparison.py"
spec_comp = importlib.util.spec_from_file_location(
    "f1_nominal_vs_half_native_labels_comparison", COMPARISON_PATH
)
assert spec_comp and spec_comp.loader
label_comparison = importlib.util.module_from_spec(spec_comp)
spec_comp.loader.exec_module(label_comparison)


def test_clone_transformer_preserves_historical_casedef_and_reverse_bytes(tmp_path: Path):
    synthetic_xml = """<?xml version="1.0" encoding="UTF-8" ?>
<case>
    <casedef>
        <constantsdef>
            <cflnumber value="0.2" />
        </constantsdef>
    </casedef>
    <execution>
        <parameters>
            <parameter key="CoefDtMin" value="0.025" />
            <parameter key="TimeMax" value="1.6" />
        </parameters>
        <constants>
            <cflnumber value="0.1" />
            <rhop0 value="1000" />
        </constants>
    </execution>
</case>
"""
    transformed = clone_transformer.transform_execution_xml(
        synthetic_xml,
        baseline_cfl=0.1,
        baseline_coef_dt_min=0.025,
        candidate_cfl=0.05,
        candidate_coef_dt_min=0.0125,
    )

    # 1. Historical casedef remains untouched
    assert '<cflnumber value="0.2" />' in transformed
    head_orig = synthetic_xml[: synthetic_xml.index("<execution>")]
    assert transformed.startswith(head_orig)

    # 2. Execution parameters are updated
    assert '<cflnumber value="0.05" />' in transformed
    assert '<parameter key="CoefDtMin" value="0.0125" />' in transformed

    # 3. Test full prepare_quarterstep_inputs
    src_xml = tmp_path / "half.xml"
    src_bi4 = tmp_path / "half.bi4"
    src_xml.write_text(synthetic_xml)
    src_bi4.write_bytes(b"SYNTHETIC_BI4_LATTICE_BYTES_012")
    bi4_hash = clone_transformer.sha256(src_bi4)

    binding_data = {
        "case_id": "TEST_QUARTERSTEP_001",
        "halfstep_cfl": 0.1,
        "halfstep_coef_dt_min": 0.025,
        "candidate_quarterstep_cfl": 0.05,
        "candidate_quarterstep_coef_dt_min": 0.0125,
        "physical_condition_sha256": "b61c7f08a1c1daa97af9340c4743123d38b48c7bd94d5ccf382d06ef5f3fd3bb",
        "source_halfstep_input_preparation": {
            "prepared_xml": str(src_xml),
            "prepared_bi4": str(src_bi4),
            "prepared_bi4_sha256": bi4_hash,
        },
    }
    binding_file = tmp_path / "test_binding.json"
    binding_file.write_text(json.dumps(binding_data))

    out_dir = tmp_path / "prepared_quarter"
    report = clone_transformer.prepare_quarterstep_inputs(binding_file, out_dir)

    assert report["historical_casedef_untouched"] is True
    assert report["whole_xml_reversebytes_verified"] is True
    assert report["initial_bi4_byte_identical"] is True
    assert (out_dir / "TEST_QUARTERSTEP_001.bi4").read_bytes() == b"SYNTHETIC_BI4_LATTICE_BYTES_012"
    assert report["q_n"] == "not_granted"


def test_nominal_vs_half_labels_comparison_synthetic(tmp_path: Path):
    nom_h5_path = tmp_path / "nom_labels.h5"
    half_h5_path = tmp_path / "half_labels.h5"
    cfg_path = tmp_path / "event-config.json"

    event_config = {
        "frame_kind": "fixed_solver_frame",
        "coordinate_frame": "case xyz",
        "destination_regions": [
            {"id": "upstream", "bounds": [[0, 1], [0, 1], [0, 1]]},
            {"id": "lower_channel", "bounds": [[1, 2], [0, 0.5], [0, 1]]},
            {"id": "upper_channel", "bounds": [[1, 2], [0.5, 1], [0, 1]]},
            {"id": "downstream", "bounds": [[2, 3], [0, 1], [0, 1]]},
        ],
        "events": [
            {"id": "lower_channel_entry", "axis": 0, "value": 1.0, "aperture_bounds": [[0, 0.5], [0, 1]]},
            {"id": "upper_channel_entry", "axis": 0, "value": 1.0, "aperture_bounds": [[0.5, 1], [0, 1]]},
            {"id": "downstream_arrival", "axis": 0, "value": 2.0, "aperture_bounds": [[0, 1], [0, 1]]},
        ],
    }
    cfg_path.write_text(json.dumps(event_config))

    nt = 1601
    np_total = 5
    # 3 fluid particles (mass 0.1), 2 fixed particles (mass 0.0)
    masses = np.array([0.1, 0.1, 0.1, 0.0, 0.0], dtype=np.float64)
    p_ids = np.arange(np_total, dtype=np.int32)
    p_zones = np.zeros(np_total, dtype=np.int32)
    times = np.linspace(0.0, 1.6, nt, dtype=np.float64)

    for path, is_half in [(nom_h5_path, False), (half_h5_path, True)]:
        with h5py.File(path, "w") as h:
            h.attrs.update(
                schema="ds-data-02.native-labels.v1",
                complete=True,
                coordinate_frame="case xyz",
                config_json=json.dumps(event_config),
            )
            h.create_dataset("time", data=times)
            h.create_dataset("particle_id", data=p_ids)
            h.create_dataset("particle_zone", data=p_zones)
            h.create_dataset("initial_fluid_mass_kg", data=masses)

            # Censors: event 0
            # particle 0: both observed (0)
            # particle 1: nom observed (0), half censored (1)
            # particle 2: both observed (0)
            # particle 3, 4: fixed (censored 1)
            censor = np.ones((np_total, 3), dtype=np.int8)
            censor[0, 0] = 0
            censor[1, 0] = 1 if is_half else 0
            censor[2, 0] = 0
            h.create_dataset("first_passage_censor", data=censor)

            chord_times = np.zeros((np_total, 3), dtype=np.float64)
            # particle 0 has 0.0001s chord delta between nom (0.5000) and half (0.5001)
            chord_times[0, 0] = 0.5001 if is_half else 0.5000
            chord_times[2, 0] = 0.6000
            h.create_dataset("first_passage_chord_time", data=chord_times)

            intervals = np.zeros((np_total, 3, 2), dtype=np.float64)
            intervals[0, 0] = [0.500, 0.501] if is_half else [0.499, 0.501]
            intervals[2, 0] = [0.599, 0.601]
            h.create_dataset("first_passage_interval", data=intervals)

            # Residence
            res = np.zeros((np_total, 4), dtype=np.float64)
            res[0, 0] = 1.0 if not is_half else 1.002
            res[1, 1] = 0.5
            res[2, 2] = 0.8
            h.create_dataset("residence_time_s", data=res)

            # Final category:
            # particle 0: 1 -> 1 (no switch)
            # particle 1: 1 -> 2 (FATE SWITCH!)
            # particle 2: 2 -> 2 (no switch)
            # particle 3, 4: 0 -> 0
            final_cat = np.array([1, 2 if is_half else 1, 2, 0, 0], dtype=np.int16)
            h.create_dataset("final_category", data=final_cat)

            # Unknown exclusions timelines
            h.create_dataset("unknown_mass_kg", data=np.zeros(nt, dtype=np.float64))
            h.create_dataset("numerical_loss_mass_kg", data=np.zeros(nt, dtype=np.float64))
            h.create_dataset("invalid_state_mass_kg", data=np.zeros(nt, dtype=np.float64))

    out_json = tmp_path / "comparison.json"
    result = label_comparison.compare_nominal_vs_half_labels(
        nominal_labels_path=nom_h5_path,
        half_labels_path=half_h5_path,
        event_config_path=cfg_path,
        output_path=out_json,
        verify_hashes=False,
    )

    assert result["cohort"]["fluid_particles"] == 3
    assert result["cohort"]["total_particles"] == 5

    # Check event 0 censor breakdown
    ev0 = result["first_passage_events"][0]
    assert ev0["censor_breakdown"]["both_observed"]["count"] == 2
    assert ev0["censor_breakdown"]["nominal_only_observed"]["count"] == 1
    assert ev0["censor_breakdown"]["halfstep_only_observed"]["count"] == 0

    # Timing check: particle 0 delta was 0.0001 s <= budget (0.000699 s)
    assert ev0["timing_statistics"]["chord_time_max_absolute_difference_s"] == pytest.approx(0.0001)
    assert ev0["timing_statistics"]["chord_time_max_within_allocated_budget"] is True

    # Fate switch check: particle 1 switched from 1 to 2
    assert result["fate_switches"]["total_switched_particles"] == 1
    assert result["fate_switches"]["total_switched_mass_kg"] == pytest.approx(0.1)
    assert "No invented distribution/CDF/chaos gate" in result["fate_switches"]["policy_mandate"]

    transitions = result["fate_switches"]["transition_matrix"]
    switch_entry = [t for t in transitions if t["nominal_category"] == 1 and t["halfstep_category"] == 2]
    assert len(switch_entry) == 1
    assert switch_entry[0]["is_switch"] is True
    assert switch_entry[0]["particle_count"] == 1

    assert result["claim_boundary"]["q_n"] == "not_granted"


def test_requests_and_bindings_invariants():
    files_to_check = [
        "quarterstep_binding.json",
        "quarterstep_prepare_request.json",
        "quarterstep_solver_request.json",
        "quarterstep_macro_binding.json",
        "quarterstep_macro_request.json",
        "nominal_vs_half_labels_binding.json",
        "nominal_vs_half_labels_request.json",
    ]

    for filename in files_to_check:
        filepath = HANDOFF_DIR / filename
        assert filepath.exists(), f"Missing file: {filename}"
        data = json.loads(filepath.read_text())

        # If it's a runner request
        if "schema" in data and "runner-request" in data["schema"]:
            assert data["launch_allowed"] is False, f"{filename}: launch_allowed must be false"
            assert data["production_approval"] == "none", f"{filename}: production_approval must be none"
            assert data["q_n_status"] == "not_granted", f"{filename}: q_n_status must be not_granted"

        # Check claim boundaries or root fields
        if "q_n" in data:
            assert data["q_n"] == "not_granted", f"{filename}: q_n must be not_granted"
        if "claim_boundary" in data and isinstance(data["claim_boundary"], dict):
            assert data["claim_boundary"].get("q_n") == "not_granted"
            assert data["claim_boundary"].get("production_approval") == "none"

        # Check realhalf013 bounded resource evidence
        if "realhalf013_evidence" in data:
            ev = data["realhalf013_evidence"]
            assert ev["elapsed_seconds"] == pytest.approx(250.62711460795254)
            assert ev["total_steps"] == 70174
            assert ev["dts_adjusted_to_dtmin"] == 0
            assert "168.1" in ev["no_nominal2x_assumption"]

        # Check bounded resource estimate in solver request
        if "bounded_resource_rationale" in data:
            rat = data["bounded_resource_rationale"]
            assert rat["realhalf013_elapsed_seconds"] == pytest.approx(250.62711460795254)
            assert rat["realhalf013_steps"] == 70174
            assert rat["realhalf013_dts_adjusted_to_dtmin"] == 0
            assert "168.1" in rat["refutation_of_nominal2x"]
