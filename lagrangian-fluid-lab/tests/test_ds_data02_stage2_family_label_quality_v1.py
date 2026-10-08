from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import h5py
import numpy as np
import pytest


ROOT = Path(__file__).parents[1]
QUALITY_SCRIPT = ROOT / "scripts/ds_data02_stage2_family_label_quality_v1.py"
NATIVE_SCRIPT = ROOT / "scripts/ds_data02_native_labels.py"
quality_spec = importlib.util.spec_from_file_location("family_label_quality", QUALITY_SCRIPT)
assert quality_spec and quality_spec.loader
QUALITY = importlib.util.module_from_spec(quality_spec)
quality_spec.loader.exec_module(QUALITY)
native_spec = importlib.util.spec_from_file_location("native_labels", NATIVE_SCRIPT)
assert native_spec and native_spec.loader
NATIVE = importlib.util.module_from_spec(native_spec)
native_spec.loader.exec_module(NATIVE)


def _source_and_config(tmp_path: Path) -> tuple[Path, Path, dict]:
    source = tmp_path / "trajectory.h5"
    position = np.array([
        [[.25, .5, .5], [.25, .5, .5], [.25, .5, .5], [.25, .5, .5]],
        [[1.25, .5, .5], [.25, .5, .5], [.25, .5, .5], [.25, .5, .5]],
        [[1.25, .5, .5], [.25, .5, .5], [np.nan, np.nan, np.nan], [.25, .5, .5]],
    ])
    with h5py.File(source, "w") as handle:
        handle.attrs["coordinate_frame"] = "fixed_tank"
        handle.create_dataset("time", data=[0.0, 1.0, 2.0])
        handle.create_dataset("particle_id", data=[1, 2, 3, 4])
        handle.create_dataset("particle_zone", data=[0, 0, 0, 0])
        handle.create_dataset("valid", data=[[1, 1, 1, 1], [1, 1, 1, 1], [1, 1, 0, 1]])
        handle.create_dataset("position", data=position)
        handle.create_dataset("mass", data=[[2.0, 3.0, 5.0, 7.0]] * 3)
        handle.create_dataset("type", data=[[3, 3, 3, 2]] * 3)
    config = {
        "frame_kind": "fixed_solver_frame",
        "coordinate_frame": "fixed_tank",
        "source_regions": [{"id": "all", "native_mk": 10, "bounds": [[0, 2], [0, 1], [0, 1]]}],
        "destination_regions": [
            {"id": "left", "bounds": [[0, 1], [0, 1], [0, 1]]},
            {"id": "right", "bounds": [[1, 2], [0, 1], [0, 1]]},
        ],
        "events": [{"id": "cross", "axis": 0, "value": 1.0, "aperture_bounds": [[0, 1], [0, 1]]}],
        "source_assignment": "initial_regions",
    }
    # Use initial-region assignment for this fixture; the exact native-MK
    # assignment is covered by the upstream native-label tests.
    config.pop("source_regions")
    config["source_regions"] = [{"id": "all", "bounds": [[0, 2], [0, 1], [0, 1]]}]
    return source, tmp_path / "labels.h5", config


def _report(source: Path, labels: Path, config: dict) -> dict:
    source_sha = QUALITY.sha256_file(source)
    labels_sha = QUALITY.sha256_file(labels)
    return {
        "schema": QUALITY.REPORT_SCHEMA,
        "status": "LABELS_MATERIALIZED_SOURCE_BOUND",
        "family_id": "F3",
        "physical_case_id": "F3_TEST_CASE",
        "source_join": {
            "family_id": "F3",
            "physical_case_id": "F3_TEST_CASE",
            "trajectory": str(source.resolve()),
            "trajectory_sha256": source_sha,
            "config_json": config,
            "raw_solver_output": str(source.parent / "solver_output"),
            "source_bindings": {
                "current_manifest": {"path": str((source.parent / "CURRENT336.json").resolve())},
            },
        },
        "label_engine": {
            "saved_frame_chords": True,
            "hidden_continuous_events": "UNKNOWN",
            "moving_frame": "UNSUPPORTED_WITHOUT_BOUND_TRANSFORMS",
        },
        "materialization": {
            "path": str(labels.resolve()),
            "sha256": labels_sha,
        },
        "observed_label_summary": {"initial_fluid_mass_kg": 10.0},
        "mass_gate": {"whole_initial_fraction_gate": 0.003, "screen_only": True, "qualification_credit": "none"},
        "physical_fate": "UNKNOWN",
        "dynamic_impact": "UNKNOWN",
        "q_n_status": "not_assessed",
        "q_e_status": "not_assessed",
        "model_invoked": False,
    }


def test_audit_validates_source_mk_mass_and_saved_bracket_censoring(tmp_path: Path) -> None:
    source, labels, config = _source_and_config(tmp_path)
    NATIVE.materialize(source, labels, config)
    report_path = tmp_path / "label-report.json"
    report_path.write_text(json.dumps(_report(source, labels, config)), encoding="utf-8")
    result = QUALITY._audit_entry(report_path, labels, "development", entry_key="F3_TEST_CASE")
    assert result["status"] == "LABEL_QUALITY_PASS_SOURCE_BOUND_MASS_CENSOR_AUDIT"
    assert result["mass_weighted_scope"]["whole_initial_denominator_kg"] == pytest.approx(10.0)
    assert result["mass_weighted_scope"]["qualification_credit"] == "none"
    assert result["censoring_scope"]["first_passage"] == "first observed saved-frame chord bracket only"
    assert result["quality_checks"]["per_frame_mass_ledger_closed"] is True


def test_audit_rejects_changed_mass_ledger_and_keeps_report_immutable(tmp_path: Path) -> None:
    source, labels, config = _source_and_config(tmp_path)
    NATIVE.materialize(source, labels, config)
    report_path = tmp_path / "label-report.json"
    report_path.write_text(json.dumps(_report(source, labels, config)), encoding="utf-8")
    with h5py.File(labels, "r+") as handle:
        handle["unknown_mass_kg"][1] = 123.0
    with pytest.raises(QUALITY.QualityError, match="producer report"):
        QUALITY._audit_entry(report_path, labels, "development", entry_key="F3_TEST_CASE")


def _minimal_report(tmp_path: Path, family: str, physical: str, trajectory_sha: str,
                    labels: Path, current: Path) -> Path:
    report = {
        "schema": QUALITY.REPORT_SCHEMA,
        "status": "LABELS_MATERIALIZED_SOURCE_BOUND",
        "family_id": family,
        "physical_case_id": physical,
        "source_join": {
            "family_id": family,
            "physical_case_id": physical,
            "trajectory_sha256": trajectory_sha,
            "source_bindings": {"current_manifest": {"path": str(current)}},
        },
        "label_engine": {
            "saved_frame_chords": True,
            "hidden_continuous_events": "UNKNOWN",
            "moving_frame": "UNSUPPORTED_WITHOUT_BOUND_TRANSFORMS",
        },
        "materialization": {"path": str(labels), "sha256": "a" * 64},
        "observed_label_summary": {},
        "mass_gate": {"screen_only": True, "qualification_credit": "none"},
        "physical_fate": "UNKNOWN",
        "dynamic_impact": "UNKNOWN",
        "q_n_status": "not_assessed",
        "q_e_status": "not_assessed",
        "model_invoked": False,
    }
    path = tmp_path / f"{physical}.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def test_manifest_rejects_family_split_leakage(tmp_path: Path) -> None:
    current = tmp_path / "CURRENT336.json"
    current.write_text("{}\n", encoding="utf-8")
    labels_a, labels_b = tmp_path / "a.h5", tmp_path / "b.h5"
    labels_a.write_bytes(b"a")
    labels_b.write_bytes(b"b")
    a = _minimal_report(tmp_path, "F3", "F3_A", "1" * 64, labels_a, current)
    b = _minimal_report(tmp_path, "F3", "F3_B", "2" * 64, labels_b, current)
    entries = [
        {"entry_key": "a", "family_id": "F3", "physical_case_id": "F3_A", "report": str(a), "labels_h5": str(labels_a), "split": "development"},
        {"entry_key": "b", "family_id": "F3", "physical_case_id": "F3_B", "report": str(b), "labels_h5": str(labels_b), "split": "recovery_safe", "recovery_policy": {
            "append_only_output": True, "no_source_mutation": True, "overwrite_forbidden": True, "qualification_credit": "none"
        }},
    ]
    with pytest.raises(QUALITY.QualityError, match="split across"):
        QUALITY.make_manifest(entries, tmp_path / "manifest.json")


def test_request_builder_defers_label_h5_hash_and_forbids_raw_trajectory_reads(tmp_path: Path) -> None:
    current = tmp_path / "CURRENT336.json"
    current.write_text("{}\n", encoding="utf-8")
    labels_a, labels_b = tmp_path / "a.h5", tmp_path / "b.h5"
    labels_a.write_bytes(b"a")
    labels_b.write_bytes(b"b")
    a = _minimal_report(tmp_path, "F3", "F3_A", "1" * 64, labels_a, current)
    b = _minimal_report(tmp_path, "F4", "F4_B", "2" * 64, labels_b, current)
    entries = [
        {"entry_key": "a", "family_id": "F3", "physical_case_id": "F3_A", "report": str(a), "labels_h5": str(labels_a), "split": "development"},
        {"entry_key": "b", "family_id": "F4", "physical_case_id": "F4_B", "report": str(b), "labels_h5": str(labels_b), "split": "recovery_safe", "recovery_policy": {
            "append_only_output": True, "no_source_mutation": True, "overwrite_forbidden": True, "qualification_credit": "none"
        }},
    ]
    manifest = tmp_path / "manifest.json"
    QUALITY.make_manifest(entries, manifest)
    root = tmp_path / "worktree"
    scripts = root / "lagrangian-fluid-lab" / "scripts"
    scripts.mkdir(parents=True)
    for name in (
        "ds_data02_stage2_family_label_quality_v1.py",
        "ds_data02_stage2_dispatch_v8.py",
        "ds_data02_strict_dispatch_v8.py",
        "ds_data02_runtime_v8.py",
    ):
        (scripts / name).write_text("# fixture\n", encoding="utf-8")
    request = QUALITY.make_request(manifest, tmp_path / "request.json", root)
    assert request["source_cost"]["original_trajectory_h5_bytes_read"] == 0
    assert request["source_cost"]["part_bi4_bytes_read"] == 0
    assert request["source_cost"]["h5_prepare_hash_deferred_to_guard"] is True
    assert request["input_sha256"][str(labels_a.resolve())] == "a" * 64
    assert request["input_sha256"][str(labels_b.resolve())] == "a" * 64
    assert request["launch_allowed"] is True
