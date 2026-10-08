from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "ds_data02_stage2_f4_s1_stream_v3_validate_v2.py"
SPEC = importlib.util.spec_from_file_location("stage2_f4_s1_stream_v3_validate_v2", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


PREFIX = "f4_drop_gap0p22000_xoff0p00000_yoff0p00000_uz0p50000"
VARIANTS = (
    ("coarse-native", "coarse", "native"),
    ("medium-native", "medium", "native"),
    ("fine-native", "fine", "native"),
    ("fine-half_dt", "fine", "half_dt"),
    ("fine-half_save", "fine", "half_save"),
)


def _event_data() -> dict:
    return {
        "pool": {
            "candidate_plane_crossings": 2,
            "outside_aperture_crossings": 0,
            "accepted_saved_crossings": 2,
            "first_saved_crossings": 1,
            "later_saved_crossings": 1,
            "positive_saved_crossings": 1,
            "negative_saved_crossings": 1,
            "accepted_saved_initial_mass_kg": 2.0,
            "finite_aperture_saved_mass_time_kg_s": 2.0,
            "finite_aperture_saved_frame_count": 2,
            "first_passage_bracket_s": [0.0, 1.0],
            "per_typed_identity": {
                "0:1": {
                    "total_saved_crossings": 2,
                    "first_saved_crossings": 1,
                    "later_saved_crossings": 1,
                    "positive_saved_crossings": 1,
                    "negative_saved_crossings": 1,
                    "saved_initial_mass_kg": 1.0,
                    "first_bracket_s": [0.0, 1.0],
                    "first_direction": "positive_x",
                    "later_brackets_s": [[1.0, 2.0]],
                }
            },
        },
        "falling_drop": {
            "candidate_plane_crossings": 1,
            "outside_aperture_crossings": 1,
            "accepted_saved_crossings": 0,
            "first_saved_crossings": 0,
            "later_saved_crossings": 0,
            "positive_saved_crossings": 0,
            "negative_saved_crossings": 0,
            "accepted_saved_initial_mass_kg": 0.0,
            "finite_aperture_saved_mass_time_kg_s": 1.0,
            "finite_aperture_saved_frame_count": 1,
            "first_passage_bracket_s": None,
            "per_typed_identity": {},
        },
    }


def _csv_text(scale: float) -> str:
    fields = [
        "frame", "time_s", "active_fluid_mass_kg", "unknown_fluid_mass_kg",
        "cumulative_unique_unknown_fluid_mass_kg", "active_momentum_x_kg_m_s",
        "active_momentum_y_kg_m_s", "active_momentum_z_kg_m_s", "active_kinetic_energy_j",
        "pool_active_mass_kg", "pool_finite_aperture_mass_kg", "pool_finite_aperture_particles",
        "pool_momentum_x_kg_m_s", "pool_momentum_y_kg_m_s", "pool_momentum_z_kg_m_s", "pool_kinetic_energy_j",
        "falling_drop_active_mass_kg", "falling_drop_finite_aperture_mass_kg", "falling_drop_finite_aperture_particles",
        "falling_drop_momentum_x_kg_m_s", "falling_drop_momentum_y_kg_m_s", "falling_drop_momentum_z_kg_m_s", "falling_drop_kinetic_energy_j",
    ]
    rows = []
    for frame, time_s in enumerate((0.0, 1.0, 2.0)):
        values = {
            "frame": frame, "time_s": time_s, "active_fluid_mass_kg": 3.0 * scale,
            "unknown_fluid_mass_kg": 0.0, "cumulative_unique_unknown_fluid_mass_kg": 0.0,
            "active_momentum_x_kg_m_s": 1.0 * scale, "active_momentum_y_kg_m_s": 0.0,
            "active_momentum_z_kg_m_s": 0.0, "active_kinetic_energy_j": 2.0 * scale,
            "pool_active_mass_kg": 2.0 * scale, "pool_finite_aperture_mass_kg": 1.0 * scale,
            "pool_finite_aperture_particles": 1, "pool_momentum_x_kg_m_s": 1.0 * scale,
            "pool_momentum_y_kg_m_s": 0.0, "pool_momentum_z_kg_m_s": 0.0,
            "pool_kinetic_energy_j": 1.0 * scale, "falling_drop_active_mass_kg": 1.0 * scale,
            "falling_drop_finite_aperture_mass_kg": 0.5 * scale, "falling_drop_finite_aperture_particles": 1,
            "falling_drop_momentum_x_kg_m_s": 0.0, "falling_drop_momentum_y_kg_m_s": 0.0,
            "falling_drop_momentum_z_kg_m_s": 0.0, "falling_drop_kinetic_energy_j": 1.0 * scale,
        }
        rows.append(",".join(str(values[field]) for field in fields))
    return ",".join(fields) + "\n" + "\n".join(rows) + "\n"


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    manifest = {
        "schema": MODULE.MANIFEST_SCHEMA,
        "family_id": "F4",
        "case_id": "F4_DROP_gap0p22000_xoff0p00000_yoff0p00000_uz0p50000",
        "physical_binding_sha256": "a" * 64,
        "source_evidence": {"path": "/producer/f4-evidence.json", "sha256": "e" * 64},
        "artifacts": [],
    }
    report = {
        "schema": MODULE.V3_REPORT_SCHEMA,
        "manifest": {},
        "source_evidence": manifest["source_evidence"],
        "artifacts": [],
    }
    for index, (variant, resolution, time_variant) in enumerate(VARIANTS):
        artifact_id = f"{PREFIX}-{variant}"
        h5_sha = f"{index + 1:064x}"
        source_binding = {key: {"path": f"/producer/{variant}-{key}.json", "sha256": f"{index + 11:064x}"} for key in ("definition_xml", "gencase_receipt", "generated_xml", "owner_metadata_source", "solver_log", "solver_receipt")}
        source_files = {key: {"path": f"/producer/{variant}-{key}.json", "sha256": f"{index + 21:064x}"} for key in ("metadata", "conversion_report", "conversion_receipt", "source_regions")}
        manifest["artifacts"].append({"artifact_id": artifact_id, "case_id": manifest["case_id"], "resolution": resolution, "time_variant": time_variant, "physical_binding_sha256": manifest["physical_binding_sha256"], "trajectory_hdf5": {"path": f"/producer/{variant}.h5", "sha256": h5_sha}, **source_files, "source_binding": source_binding})
        artifact_dir = tmp_path / "artifacts" / artifact_id
        artifact_dir.mkdir(parents=True)
        curve_path = artifact_dir / "typed-science-timeseries-v3.csv"
        labels_path = artifact_dir / "typed-science-labels-v3.json"
        curve_path.write_text(_csv_text(1.0 + 0.01 * index), encoding="utf-8")
        events = _event_data()
        labels_path.write_text(json.dumps(events, sort_keys=True) + "\n", encoding="utf-8")
        report["artifacts"].append({
            "artifact_id": artifact_id, "case_id": manifest["case_id"], "resolution": resolution, "time_variant": time_variant, "physical_binding_sha256": manifest["physical_binding_sha256"],
            "frames": 3, "particles": 3, "trajectory_hdf5": {"declared_sha256": h5_sha, "worker_rehashed": False},
            "whole_initial_fluid_mass_kg": 3.0, "source_event_data": events,
            **source_files, "source_binding": source_binding,
            "curve": {"path": str(curve_path), "sha256": hashlib.sha256(curve_path.read_bytes()).hexdigest()},
            "labels": {"path": str(labels_path), "sha256": hashlib.sha256(labels_path.read_bytes()).hexdigest()},
        })
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    report["manifest"] = {"path": str(manifest_path), "sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest()}
    report_path = tmp_path / "f4-s1-stream-v3-report.json"
    report_path.write_text(json.dumps(report, sort_keys=True) + "\n", encoding="utf-8")
    return report_path, manifest_path


def test_validator_separates_spatial_proxy_integral_and_sampling(tmp_path):
    report_path, manifest_path = _fixture(tmp_path)
    output_path = tmp_path / "validation.json"
    result = MODULE.validate(report_path=report_path, manifest_path=manifest_path, output_path=output_path)
    assert set(result["artifacts"]) == set(MODULE.EXPECTED_VARIANTS)
    assert "coarse-native" in result["spatial_proxy"]
    assert "coarse-native" in result["integral"]
    assert "fine-half_save" in result["save_sampling"]
    assert result["claim_boundary"]["continuous_event_time"] == "unknown"
    assert result["claim_boundary"]["qualification_credit"] == "not_granted"
    assert result["tolerance_basis"]["qualification_credit"] == "not granted"
    assert result["frozen_tolerances"]["whole_initial_unknown_mass_fraction_max"] == 0.003
    assert result["frozen_tolerances"]["mass_preferred_relative_max"] == 0.01
    assert result["frozen_tolerances"]["mass_marginal_relative_max"] == 0.02
    assert result["frozen_tolerances"]["mass_hard_relative_max"] == 0.02
    assert result["frozen_tolerances"]["position_relative_domain_length_max"] == 0.02
    assert result["frozen_tolerances"]["velocity_kinetic_energy_relative_nonzero_max"] == 0.05
    assert result["frozen_tolerances"]["event_time_relative_window_max"] == 0.01
    assert result["frozen_tolerances"]["integration_output_allocation_each_fraction"] == 0.25
    assert "region_flux" in result
    assert result["save_sampling"]["coarse-native"]["endpoint_status"] == "reported_without_frozen_endpoint_gate"
    assert "spatial_proxy_relative_linf" not in result["frozen_tolerances"]
    assert result["spatial_proxy"]["medium-native"]["metrics"]["active_fluid_mass_kg"]["diagnostic_status"] == "within_mass_preferred_diagnostic_band"
    assert result["spatial_proxy"]["coarse-native"]["metrics"]["active_fluid_mass_kg"]["diagnostic_status"] == "within_mass_marginal_diagnostic_band"
    assert output_path.is_file()


def test_validator_rejects_report_that_rehashes_h5_or_miscounts_crossings(tmp_path):
    report_path, manifest_path = _fixture(tmp_path)
    report = json.loads(report_path.read_text())
    report["artifacts"][0]["trajectory_hdf5"]["worker_rehashed"] = True
    report_path.write_text(json.dumps(report) + "\n")
    with pytest.raises(MODULE.ValidationError):
        MODULE.validate(report_path=report_path, manifest_path=manifest_path, output_path=tmp_path / "bad.json")
