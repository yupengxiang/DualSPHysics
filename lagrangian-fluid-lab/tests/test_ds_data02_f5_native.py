from __future__ import annotations

import csv
import json
from pathlib import Path
import sys

import h5py
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import ds_data02_f5_native as native


FAMILY = ROOT / "campaigns/ds-data-02/families/F5"


def _write_runparts(path: Path, times: np.ndarray) -> None:
    fields = ["Part", "TimeStep [s]", "NpOut", "NpOutPos", "NpOutRho", "NpOutMov", "DtMin [s]", "DtMax [s]"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter=";")
        writer.writeheader()
        for index, time_s in enumerate(times):
            writer.writerow({
                "Part": index,
                "TimeStep [s]": f"{time_s:.8f}",
                "NpOut": 0,
                "NpOutPos": 0,
                "NpOutRho": 0,
                "NpOutMov": 0,
                "DtMin [s]": 0.001,
                "DtMax [s]": 0.002,
            })


def _write_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path, Path, Path, Path]:
    hdf5_path = tmp_path / "typed.h5"
    owner_path = tmp_path / "owner.json"
    motion_path = tmp_path / "motion.dat"
    solver_output = tmp_path / "solver_output"
    event_path = tmp_path / "events.json"
    quality_path = tmp_path / "quality.json"
    output = tmp_path / "audit.json"
    preview = tmp_path / "preview.json"
    solver_output.mkdir()

    times = np.arange(native.EXPECTED_FRAMES, dtype=np.float64) * 0.02
    position = np.zeros((native.EXPECTED_FRAMES, 3, 3), dtype=np.float32)
    # Fixed and moving particles remain at x=0.  The fluid particle reaches
    # the toe, crosses the runup line, and returns, exercising every label type.
    position[:, 2, 0] = np.interp(np.arange(native.EXPECTED_FRAMES), [0, 100, 150, 250, 800], [0.0, 4.0, 7.0, 2.0, 2.0])
    position[:, 2, 2] = np.interp(np.arange(native.EXPECTED_FRAMES), [0, 100, 150, 250, 800], [0.2, 0.2, 1.0, 0.2, 0.2])
    velocity = np.zeros_like(position)
    velocity[1:, 2, 0] = np.diff(position[:, 2, 0]) / 0.02
    velocity[1:, 2, 2] = np.diff(position[:, 2, 2]) / 0.02
    valid = np.ones((native.EXPECTED_FRAMES, 3), dtype=bool)
    typed = np.tile(np.array([0, 1, 3], dtype=np.int8), (native.EXPECTED_FRAMES, 1))
    mk = np.tile(np.array([40, 20, 1], dtype=np.int16), (native.EXPECTED_FRAMES, 1))
    scalar = np.ones((native.EXPECTED_FRAMES, 3), dtype=np.float32)
    with h5py.File(hdf5_path, "w") as handle:
        handle.create_dataset("time", data=times)
        handle.create_dataset("particle_id", data=np.array([10, 11, 12], dtype=np.uint32))
        handle.create_dataset("particle_zone", data=np.zeros(3, dtype=np.int16))
        handle.create_dataset("valid", data=valid)
        handle.create_dataset("position", data=position)
        handle.create_dataset("velocity", data=velocity)
        handle.create_dataset("density", data=scalar * 1000.0)
        handle.create_dataset("mass", data=scalar)
        handle.create_dataset("pressure", data=scalar)
        handle.create_dataset("type", data=typed)
        handle.create_dataset("mk", data=mk)
        handle.create_dataset("initial_type", data=np.array([0, 1, 3], dtype=np.int8))
        handle.create_dataset("initial_mk", data=np.array([40, 20, 1], dtype=np.int16))
        handle.create_dataset("initial_mass", data=np.array([1.0, 1.0, 2.0], dtype=np.float64))

    owner_path.write_text(json.dumps({
        "source_contract": {
            "finite_source": "fixture source",
            "finite_destinations": ["upstream", "slope_crest"],
            "domain_repair_semantics": "test-only",
        }
    }) + "\n", encoding="utf-8")
    motion_path.write_text("0 0\n16 0\n", encoding="utf-8")
    (solver_output / "Run.out").write_text("**3D-Simulation parameters\nCaseNp=3\nExcluded particles: 0\nFinished execution (code=0)\n", encoding="utf-8")
    _write_runparts(solver_output / "RunPARTs.csv", times)
    event_path.write_text(json.dumps({"schema": "fixture-events"}) + "\n", encoding="utf-8")
    quality_path.write_text(json.dumps({"q_n": {"claim": "none"}}) + "\n", encoding="utf-8")
    return hdf5_path, owner_path, motion_path, solver_output, event_path, quality_path, output, preview


def test_label_registration_preserves_conversion_and_blocks_claims() -> None:
    index = json.loads((FAMILY / "native_conversion/label-registration-index-002.json").read_text(encoding="utf-8"))
    assert index["conversion_requests_unchanged"] is True
    assert index["prior_label_attempts_preserved"] is True
    assert index["max_simultaneous_labels"] == 2
    assert len(index["requests"]) == 2
    for row in index["requests"]:
        request = json.loads(Path(row["request"]).read_text(encoding="utf-8"))
        assert request["kind"] == "cpu"
        assert request["cpu_task_kind"] == "labels"
        assert request["command"][2] == "label"
        assert request["output_semantics"]["qualification_claim"] == "none"
        assert request["output_semantics"]["q_n_status"] == "not_assessed"
        assert request["retry_of"]["attempt_id"].endswith("-001")


def test_continuous_volume_audit_does_not_use_support_layer_denominator() -> None:
    audit = json.loads((FAMILY / "native_conversion/initial-continuous-volume-audit-001.json").read_text(encoding="utf-8"))
    assert audit["method"].startswith("continuous fill-box volume minus physical STL/bed-profile intersection")
    for row in audit["cases"]:
        assert row["continuous_fill_box"]["volume_m3"] == 2.352
        assert row["physical_bed_intersection"]["intersection_volume_m3"] == 0.0
        assert row["physical_bed_intersection"]["accessible_continuum_mass_kg"] == 2352.0
        assert row["native_initial_fluid"]["particles"] == 74760
        assert row["mass_comparison"]["mass_rescaling"] is False
        assert row["mass_comparison"]["absolute_relative_error"] > 0.14
        assert "dp/2" in row["interpretation"]["support_layer_explanation"]
        assert row["mass_comparison"]["qn_continuous_mass_status"] == "blocked_pending_initialization_or_contract_review"


def test_native_product_evidence_has_partvtk_and_label_bindings() -> None:
    evidence = json.loads((FAMILY / "native_conversion/native-product-evidence-001.json").read_text(encoding="utf-8"))
    assert evidence["product_status"] == "native_conversion_and_transport_audit_complete_pending_root_review"
    provenance = evidence["source_provenance_sidecar"]
    assert Path(provenance["path"]).is_file()
    assert provenance["role"].startswith("complete current F5 source provenance")
    assert evidence["qualification_claim"] == "none"
    assert len(evidence["cases"]) == 2
    for row in evidence["cases"]:
        assert row["typed_conversion"]["partvtk_validation"]["all_passed"] is True
        assert row["typed_conversion"]["frames"] == 801
        assert row["typed_conversion"]["solver_dimension"]["solver_dimension"] == 3
        assert row["transport_labels"]["schema"] == "ds-data-02.f5.transport-labels.v1"
        assert row["transport_labels"]["particles"] == 74760
        assert row["transport_labels"]["qualification_claim"] == "none"
        assert row["transport_labels"]["q_n_status"] == "not_assessed"
        assert row["raw_solver_evidence"]["complete_801_frame_window"] is True
        assert row["transport_audit"]["domain_repair_semantics"].startswith("common numerical domain extension only")


def test_transport_label_writer_emits_identity_events_and_residence(tmp_path: Path) -> None:
    hdf5_path, owner_path, motion_path, solver_output, event_path, quality_path, output, preview = _write_fixture(tmp_path)
    labels_path = tmp_path / "transport-labels.h5"
    audit = native.audit_transport(
        case_id="F5_REF_RUNUP_NOMINAL_COARSE",
        hdf5_path=hdf5_path,
        owner_path=owner_path,
        motion_path=motion_path,
        solver_output=solver_output,
        event_path=event_path,
        quality_path=quality_path,
        output=output,
        preview=preview,
        labels_path=labels_path,
    )
    assert audit["qualification_claim"] == "none"
    assert audit["q_n_status"] == "not_assessed"
    assert audit["native"]["frames"] == native.EXPECTED_FRAMES
    assert audit["transport_events"]["events"]["toe_first_arrival"]["observed_particles"] == 1
    assert audit["transport_events"]["events"]["runup_first_crossing"]["observed_particles"] == 1
    assert audit["transport_events"]["events"]["toe_return_crossing"]["observed_particles"] == 1
    assert audit["moving_piston"]["max_abs_mean_x_displacement_error_m"] == 0.0
    with h5py.File(labels_path, "r") as labels:
        assert labels.attrs["schema"] == "ds-data-02.f5.transport-labels.v1"
        assert labels.attrs["identity_key"] == "(Zone,Idp)"
        assert bool(labels.attrs["complete"]) is True
        assert labels["particle_id"][:].tolist() == [12]
        assert labels["initial_source_label"][0].decode() == "upstream_reservoir"
        assert np.isfinite(labels["first_toe_first_arrival_time_s"][:]).all()
        assert np.isfinite(labels["first_runup_first_crossing_time_s"][:]).all()
        assert np.isfinite(labels["first_toe_return_crossing_time_s"][:]).all()
        assert labels["valid_all_frames"][:].tolist() == [True]
