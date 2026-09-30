from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import h5py
import numpy as np

from scripts.ds_data02_scope import (
    CURRENT_EVIDENCE_CLASS,
    FULL_STATE_COVERAGE,
    validate_scope_documents,
    validate_scope_files,
)


ROOT = Path(__file__).resolve().parents[1]


def _write_artifact(root: Path, name: str, payload: object) -> dict[str, str]:
    path = root / name
    if isinstance(payload, bytes):
        raw = payload
    else:
        raw = json.dumps(payload, sort_keys=True).encode("utf-8")
    path.write_bytes(raw)
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


def _binding(root: Path, name: str, role: str, payload: object) -> dict[str, str]:
    value = _write_artifact(root, name, payload)
    value["role"] = role
    return value


def _recipe() -> dict[str, object]:
    return {
        "recipe_id": "F2_FIXTURE_RECIPE_V1",
        "schema": "ds-data-02.f2.full-state.v1",
        "state_schema": "ds-data-02.full-typed-state.v1",
        "view_id": "native_full_state",
        "solver_dimension": 3,
    }


def _state_requirements(*, moving: bool = True) -> dict[str, object]:
    specs = {
        "time": {"path": "time", "rank": 1, "units": "s", "time_indexed": False},
        "position": {"path": "position", "rank": 3, "last_dim": 3, "units": "m"},
        "velocity": {"path": "velocity", "rank": 3, "last_dim": 3, "units": "m/s"},
        "density": {"path": "density", "rank": 2, "units": "kg/m^3"},
        "mass": {"path": "mass", "rank": 2, "units": "kg"},
        "type": {"path": "type", "rank": 2, "units": "1"},
        "valid": {"path": "valid", "rank": 2, "units": "1"},
        "particle_id": {"path": "particle_id", "rank": 1, "units": "1", "time_indexed": False},
        "particle_zone": {"path": "particle_zone", "rank": 1, "units": "1", "time_indexed": False},
    }
    required = list(specs)
    if moving:
        specs["rigid_body_state"] = {"path": "rigid_body_state", "rank": 1, "units": "state"}
        required.append("rigid_body_state")
    return {
        "required_datasets": required,
        "dataset_specs": specs,
        "identity": {
            "axis": "(Zone,Idp)",
            "particle_id": "particle_id",
            "particle_zone": "particle_zone",
            "type": "type",
            "valid": "valid",
        },
        "type_semantics": {"fluid_values": [3], "moving_values": [1, 2], "boundary_values": [0]},
        "moving_boundary": {"mode": "conditional" if moving else "not_applicable", "dataset": "rigid_body_state" if moving else None},
        "qi_report": {"accepted_statuses": ["Q-I-structure-pass", "Q-I-pass"]},
    }


def _write_state_h5(root: Path, name: str, *, moving: bool = True) -> dict[str, str]:
    path = root / name
    frames, particles = 5, 4
    with h5py.File(path, "w") as handle:
        handle.attrs["identity_key"] = "(Zone,Idp)"
        handle.attrs["solver_dimension"] = 3
        units = {
            "time": "s", "position": "m", "velocity": "m/s", "density": "kg/m^3",
            "mass": "kg", "type": "1", "valid": "1", "particle_id": "1", "particle_zone": "1",
        }
        if moving:
            units["rigid_body_state"] = "state"
        handle.attrs["units_json"] = json.dumps(units, sort_keys=True)
        values = {
            "time": np.linspace(0.0, 4.0, frames),
            "position": np.zeros((frames, particles, 3), dtype=np.float32),
            "velocity": np.zeros((frames, particles, 3), dtype=np.float32),
            "density": np.full((frames, particles), 1000.0, dtype=np.float32),
            "mass": np.full((frames, particles), 0.1, dtype=np.float32),
            "type": np.tile(np.array([0, 1 if moving else 0, 3, 3], dtype=np.int8), (frames, 1)),
            "valid": np.ones((frames, particles), dtype=bool),
            "particle_id": np.arange(particles, dtype=np.int64),
            "particle_zone": np.zeros(particles, dtype=np.int16),
        }
        for key, value in values.items():
            dataset = handle.create_dataset(key, data=value)
            dataset.attrs["units"] = units[key]
        if moving:
            dtype = np.dtype([("time_s", "f8"), ("body_id", "i4"), ("valid", "u1"), ("position_rms_m", "f8")])
            dataset = handle.create_dataset("rigid_body_state", data=np.zeros(frames, dtype=dtype))
            dataset.attrs["units"] = "state"
    raw = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


def _observations() -> dict[str, object]:
    return {
        "required_event_names": ["cup_departure", "receiver_entry", "tray_entry", "cup_residence"],
        "units": {"time": "s", "position": "m", "velocity": "m/s", "mass": "kg"},
        "physical_scale": {
            "characteristic_length_m": 0.33,
            "characteristic_time_s": 0.18340977,
            "characteristic_velocity_m_s": 1.79924984,
        },
        "error_budget": {
            "event_time_absolute_s": 0.0036682,
            "macro_relative": 0.05,
            "integration_fraction": 0.2,
            "save_fraction": 0.2,
        },
    }


def _case(root: Path, *, background: str, mechanism: str, prefix: str) -> dict[str, object]:
    geometry_family = f"F2_GEOM_{background.upper()}_V1"
    control_family = "F2_CTRL_SMOOTH_ROTATE_Y_V1"
    physical_hash = (prefix * 64)[:64]
    recipe_hashes = {
        "coarse": ((prefix + "c") * 64)[:64],
        # Keep the fixture hashes syntactically valid SHA-256 values.  The
        # validator intentionally rejects mnemonic non-hex placeholders.
        "medium": ((prefix + "d") * 64)[:64],
        "fine": ((prefix + "e") * 64)[:64],
    }
    return {
        "case_id": f"F2_{background.upper()}_P01",
        "physical_case_id": f"F2_{background.upper()}_P01",
        "parent_group_id": "F2_PAIR_01",
        "split": "train",
        "background": background,
        "mechanism_id": mechanism,
        "geometry_family_id": geometry_family,
        "control_family_id": control_family,
        "physical_condition_hash": physical_hash,
        "parameter_values": {"fill_ratio": 1.0, "receiver_x_m": 0.45, "rotation_duration_s": 1.2},
        "geometry": {"finite_wall_faces": ["cup_bottom", "receiver_bottom", "tray_bottom"], "domain_extent_m": [3.1, 1.85, 2.25]},
        "control": {"motion_axis": "+Y", "motion_sha256": "e" * 64, "rotation_end_s": 1.7},
        "resolution_views": ["coarse", "medium", "fine"],
        "qi_resolution": "coarse",
        "numeric_settings_by_resolution": {
            "coarse": {"dp_m": 0.025, "DtFixed": 0.0, "TimeOut": 0.01},
            "medium": {"dp_m": 0.02, "DtFixed": 0.0, "TimeOut": 0.01},
            "fine": {"dp_m": 0.015, "DtFixed": 0.0, "TimeOut": 0.01},
        },
        "numerical_recipe_hash_by_resolution": recipe_hashes,
        "input_bindings": [
            _binding(root, f"{prefix}-geometry.xml", "geometry", {"family": geometry_family}),
            _binding(root, f"{prefix}-motion.dat", "control", {"family": control_family}),
        ],
    }


def _scope(root: Path) -> dict[str, object]:
    cases = [
        _case(root, background="center_catch", mechanism="center_catch", prefix="a"),
        _case(root, background="offset_spill", mechanism="offset_spill", prefix="b"),
    ]
    scope = {
        "schema": "ds-data-02.scope-spec.v1",
        "family_id": "F2",
        "scope_id": "F2_FIXTURE_SCOPE_V1",
        "required_input_roles": ["quality_contract", "event_definitions", "case_registry", "reference_matrix"],
        "recipe": _recipe(),
        "time_domain": {"start_s": 0.0, "end_s": 4.0, "complete_event_window": True, "minimum_frames": 4},
        "state_requirements": _state_requirements(),
        "observations": _observations(),
        "physical_parameter_domains": {"receiver_x_m": {"min": 0.45, "max": 0.65, "units": "m"}},
        "physical_domain": {"cases": cases},
        "reference_requirements": {
            "backgrounds": ["center_catch", "offset_spill"],
            "resolutions": ["coarse", "medium", "fine"],
            "expected_view_count": 6,
            "coverage_mode": "full_family_default",
            "required_source_roles": ["geometry_xml", "gencase_bi4", "copied_motion", "solver_log"],
            "reference_case_ids": {"center_catch": cases[0]["case_id"], "offset_spill": cases[1]["case_id"]},
        },
        "comparison_requirements": [
            {
                "comparison_id": "center-integration",
                "kind": "integration",
                "case_id": cases[0]["case_id"],
                "physical_case_id": cases[0]["physical_case_id"],
                "background": "center_catch",
                "baseline_resolution": "coarse",
                "required_changed_numeric_fields": ["internal_dt_s"],
                "required_statistic_fields": ["internal_dt_s", "step_count"],
                "required_observation_points": ["endpoint", "internal"],
                "parameter_points": {
                    "endpoint": {"parameter": "receiver_x_m", "side": "min"},
                    "internal": {"parameter": "receiver_x_m"},
                },
                "required_error_metrics": ["event_time_absolute_s", "macro_relative", "integration_fraction"],
            },
            {
                "comparison_id": "offset-integration",
                "kind": "integration",
                "case_id": cases[1]["case_id"],
                "physical_case_id": cases[1]["physical_case_id"],
                "background": "offset_spill",
                "baseline_resolution": "coarse",
                "required_changed_numeric_fields": ["internal_dt_s"],
                "required_statistic_fields": ["internal_dt_s", "step_count"],
                "required_observation_points": ["endpoint", "internal"],
                "parameter_points": {
                    "endpoint": {"parameter": "receiver_x_m", "side": "min"},
                    "internal": {"parameter": "receiver_x_m"},
                },
                "required_error_metrics": ["event_time_absolute_s", "macro_relative", "integration_fraction"],
            },
            {
                "comparison_id": "center-save",
                "kind": "save",
                "case_id": cases[0]["case_id"],
                "physical_case_id": cases[0]["physical_case_id"],
                "background": "center_catch",
                "baseline_resolution": "coarse",
                "required_changed_numeric_fields": ["save_interval_s"],
                "required_statistic_fields": ["save_interval_s", "frame_count"],
                "required_observation_points": ["endpoint", "internal"],
                "parameter_points": {
                    "endpoint": {"parameter": "receiver_x_m", "side": "min"},
                    "internal": {"parameter": "receiver_x_m"},
                },
                "required_error_metrics": ["event_time_absolute_s", "macro_relative", "save_fraction"],
            },
            {
                "comparison_id": "offset-save",
                "kind": "save",
                "case_id": cases[1]["case_id"],
                "physical_case_id": cases[1]["physical_case_id"],
                "background": "offset_spill",
                "baseline_resolution": "coarse",
                "required_changed_numeric_fields": ["save_interval_s"],
                "required_statistic_fields": ["save_interval_s", "frame_count"],
                "required_observation_points": ["endpoint", "internal"],
                "parameter_points": {
                    "endpoint": {"parameter": "receiver_x_m", "side": "min"},
                    "internal": {"parameter": "receiver_x_m"},
                },
                "required_error_metrics": ["event_time_absolute_s", "macro_relative", "save_fraction"],
            },
        ],
        "input_bindings": [
            _binding(root, "quality-contract.json", "quality_contract", {"schema": "current"}),
            _binding(root, "event-definitions.json", "event_definitions", {"events": 4}),
            _binding(root, "case-registry.jsonl", "case_registry", b"F2_CASE_REGISTRY\n"),
            _binding(root, "reference-matrix.json", "reference_matrix", {"views": 6}),
        ],
    }
    return scope


def _qi(root: Path, case: dict[str, object], *, resolution: str = "coarse", tag: str | None = None) -> dict[str, object]:
    suffix = tag or resolution
    h5_binding = _write_state_h5(root, f"{case['case_id']}-{suffix}.h5")
    h5_binding["role"] = "trajectory_h5"
    report_binding = _binding(
        root,
        f"{case['case_id']}-{suffix}-qi-report.json",
        "qi_report",
        {
            "family_id": "F2",
            "case_id": case["case_id"],
            "q_i": {
                "status": "Q-I-structure-pass",
                "failed_checks": [],
                "checks": {"actual_h5_state_read": True, "typed_lifecycle_audited": True},
            },
        },
    )
    return {
        "resolution": resolution,
        "evidence_file": report_binding,
        "source_bindings": [h5_binding],
        "full_timeline": {"frames": 5, "start_s": 0.0, "end_s": 4.0},
        "observed_event_names": ["cup_departure", "receiver_entry", "tray_entry", "cup_residence"],
    }


def _evidence(root: Path, scope: dict[str, object], scope_path: Path) -> dict[str, object]:
    cases = [copy.deepcopy(case) for case in scope["physical_domain"]["cases"]]
    evidence_cases = []
    for case in cases:
        evidence_case = copy.deepcopy(case)
        evidence_case["recipe"] = _recipe()
        evidence_case["qi"] = _qi(root, case)
        evidence_cases.append(evidence_case)

    references = []
    for case in cases:
        for resolution in ["coarse", "medium", "fine"]:
            references.append({
                "background": case["background"],
                "resolution": resolution,
                "physical_case_id": case["physical_case_id"],
                "parent_group_id": case["parent_group_id"],
                "split": case["split"],
                "geometry_family_id": case["geometry_family_id"],
                "control_family_id": case["control_family_id"],
                "physical_condition_hash": case["physical_condition_hash"],
                "numerical_recipe_hash": case["numerical_recipe_hash_by_resolution"][resolution],
                "numeric_settings": case["numeric_settings_by_resolution"][resolution],
                "recipe": _recipe(),
                "evidence_class": CURRENT_EVIDENCE_CLASS,
                "state_coverage": FULL_STATE_COVERAGE,
                "status": "actual_reference_pass",
                "qi": _qi(root, case, resolution=resolution, tag=f"{case['case_id']}-{resolution}"),
                "evidence_file": _binding(root, f"{case['case_id']}-{resolution}-reference.json", "reference_report", {"status": "actual_reference_pass"}),
                "source_bindings": [
                    _binding(root, f"{case['case_id']}-{resolution}.xml", "geometry_xml", b"XML_INPUT"),
                    _binding(root, f"{case['case_id']}-{resolution}.bi4", "gencase_bi4", b"BI4_INPUT"),
                    _binding(root, f"{case['case_id']}-{resolution}.motion.dat", "copied_motion", b"MOTION_INPUT"),
                    _binding(root, f"{case['case_id']}-{resolution}.solver.log", "solver_log", b"SOLVER_LOG"),
                ],
                "solver": {
                    "completed": True,
                    "solver_dimension": 3,
                    "data2d": False,
                    "total_particles": 1000,
                    "fluid_count": 100,
                    "motion_control_covered": True,
                    "finite_boundary_covered": True,
                    "time_domain": {"complete": True, "start_s": 0.0, "end_s": 4.0},
                },
                "checks": {"three_dimensional": True, "nonzero_fluid": True, "population_bound": True, "geometry_bound": True, "control_bound": True},
            })

    comparisons = []
    for requirement in scope["comparison_requirements"]:
        case = next(case for case in cases if case["case_id"] == requirement["case_id"])
        changed = requirement["required_changed_numeric_fields"]
        stats = {"sample_count": 20, "step_count": 200, "frame_count": 80, "internal_dt_s": 0.00005, "save_interval_s": 0.001}
        comparisons.append({
            **{key: requirement[key] for key in ("comparison_id", "kind", "case_id", "physical_case_id", "background")},
            "parent_group_id": case["parent_group_id"],
            "split": case["split"],
            "physical_condition_hash": case["physical_condition_hash"],
            "recipe": _recipe(),
            "evidence_class": CURRENT_EVIDENCE_CLASS,
            "state_coverage": FULL_STATE_COVERAGE,
            "status": "actual_pass",
            "independent": True,
            "evidence_file": _binding(root, f"{requirement['comparison_id']}.json", "comparison_report", {"status": "actual_pass"}),
            "source_bindings": [_binding(root, f"{requirement['comparison_id']}.solver.log", "comparison_solver_log", b"ACTUAL_COMPARISON")],
            "baseline_numerical_recipe_hash": case["numerical_recipe_hash_by_resolution"][requirement["baseline_resolution"]],
            "comparison_numerical_recipe_hash": (("d" if requirement["kind"] == "integration" else "e") * 64),
            "changed_numeric_fields": changed,
            "actual_statistics": stats,
            "actual_error_metrics": {
                "event_time_absolute_s": 0.001,
                "macro_relative": 0.01,
                "integration_fraction": 0.1,
                "save_fraction": 0.1,
            },
            "physical_parameter_points": {
                "endpoint": {"parameter": "receiver_x_m", "value": 0.45, "sample_count": 1, "metrics": {"event_time_absolute_s": 0.001}},
                "internal": {"parameter": "receiver_x_m", "value": 0.55, "sample_count": 2, "metrics": {"event_time_absolute_s": 0.001}},
            },
            "observations": {
                "endpoint": {"sample_count": 1, "metrics": {"macro_error": 0.01}},
                "internal": {"sample_count": 10, "metrics": {"event_time_error": 0.001}},
            },
            "time_domain": {"complete": True, "start_s": 0.0, "end_s": 4.0},
        })

    scope_hash = hashlib.sha256(scope_path.read_bytes()).hexdigest()
    return {
        "schema": "ds-data-02.scope-evidence.v1",
        "family_id": "F2",
        "scope_id": scope["scope_id"],
        "evidence_class": CURRENT_EVIDENCE_CLASS,
        "state_coverage": FULL_STATE_COVERAGE,
        "recipe": _recipe(),
        "scope_binding": {"role": "scope_spec", "path": str(scope_path), "sha256": scope_hash},
        "observations": copy.deepcopy(scope["observations"]),
        "cases": evidence_cases,
        "reference_views": references,
        "comparisons": comparisons,
        "q_e": {"status": "optional", "external_match": None},
        "other_family_evidence": {"family_id": "F3", "status": "ignored"},
        "material_tracer": {"used": False},
        "model": {"used": False},
    }


def _write_fixture(tmp_path: Path) -> tuple[Path, Path]:
    scope = _scope(tmp_path)
    scope_path = tmp_path / "scope.json"
    scope_path.write_text(json.dumps(scope, indent=2), encoding="utf-8")
    evidence = _evidence(tmp_path, scope, scope_path)
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return scope_path, evidence_path


def _codes(verdict: dict[str, object]) -> set[str]:
    return {str(item["code"]) for item in verdict["errors"]}


def test_current_full_scope_evidence_is_eligible_but_not_approved(tmp_path: Path) -> None:
    scope_path, evidence_path = _write_fixture(tmp_path)
    evidence = json.loads(evidence_path.read_text())
    # These optional domains are explicitly outside this validator's gate.
    evidence["q_e"]["qualified"] = True
    evidence["other_family_evidence"]["production_eligible"] = True
    evidence["model"]["qualified"] = True
    evidence_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    verdict = validate_scope_files(scope_path, evidence_path)

    assert verdict["status"] == "evidence-bound-eligible"
    assert verdict["evidence_bound_eligible"] is True
    assert verdict["approval_authority"] == "root-approved-index-only"
    assert verdict["approval_index_write"] == "not_performed"
    assert verdict["checks"]["reference_matrix"] is True
    assert verdict["checks"]["independent_comparisons"] is True
    assert len(verdict["bound_artifacts"]) >= 20


def test_reuse_requires_full_state_and_exact_scope_equivalence(tmp_path: Path) -> None:
    scope_path, evidence_path = _write_fixture(tmp_path)
    scope = json.loads(scope_path.read_text())
    evidence = json.loads(evidence_path.read_text())
    old_scope = copy.deepcopy(scope)
    old_scope["qualified"] = True
    old_scope_binding = _binding(tmp_path, "old-qualified-scope.json", "source_scope", old_scope)
    equivalence = _binding(tmp_path, "reuse-equivalence.json", "scope_equivalence_report", {"equivalent": True})
    evidence["reuse"] = {
        "strict_scope_equivalence": True,
        "source_state_coverage": FULL_STATE_COVERAGE,
        "equivalent_scope_binding": old_scope_binding,
        "equivalence_evidence": [equivalence],
    }
    evidence_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")

    verdict = validate_scope_files(scope_path, evidence_path)

    assert verdict["evidence_bound_eligible"] is True


def test_parent_split_leakage_is_rejected_even_with_hash_bound_artifacts(tmp_path: Path) -> None:
    scope_path, evidence_path = _write_fixture(tmp_path)
    scope = json.loads(scope_path.read_text())
    scope["physical_domain"]["cases"][1]["split"] = "validation"
    scope_path.write_text(json.dumps(scope, indent=2), encoding="utf-8")

    verdict = validate_scope_files(scope_path, evidence_path)

    assert verdict["evidence_bound_eligible"] is False
    assert "scope_parent_split_leak" in _codes(verdict)


def test_supplied_digest_is_checked_against_bytes(tmp_path: Path) -> None:
    scope_path, evidence_path = _write_fixture(tmp_path)
    scope = json.loads(scope_path.read_text())
    evidence = json.loads(evidence_path.read_text())

    verdict = validate_scope_documents(
        scope,
        evidence,
        scope_path=scope_path,
        evidence_path=evidence_path,
        scope_sha256="0" * 64,
        evidence_sha256=hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
    )

    assert verdict["evidence_bound_eligible"] is False
    assert "scope_input_hash_mismatch" in _codes(verdict)


def test_actual_h5_fluid_type_tampering_is_rejected_even_after_hash_rebinding(tmp_path: Path) -> None:
    scope_path, evidence_path = _write_fixture(tmp_path)
    evidence = json.loads(evidence_path.read_text())
    h5_binding = evidence["cases"][0]["qi"]["source_bindings"][0]
    h5_path = Path(h5_binding["path"])
    with h5py.File(h5_path, "r+") as handle:
        handle["type"][0, 2:] = 0
    h5_binding["sha256"] = hashlib.sha256(h5_path.read_bytes()).hexdigest()
    evidence_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")

    verdict = validate_scope_files(scope_path, evidence_path)

    assert verdict["evidence_bound_eligible"] is False
    assert "state_fluid_population_zero" in _codes(verdict)


def test_time_frame_cannot_be_substituted_for_physical_parameter_internal_point(tmp_path: Path) -> None:
    scope_path, evidence_path = _write_fixture(tmp_path)
    evidence = json.loads(evidence_path.read_text())
    comparison = evidence["comparisons"][0]
    comparison.pop("physical_parameter_points")
    comparison["observations"]["internal"]["time_s"] = 2.0
    evidence_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")

    verdict = validate_scope_files(scope_path, evidence_path)

    assert verdict["evidence_bound_eligible"] is False
    assert "comparison_parameter_points_missing" in _codes(verdict)


def test_failed_numeric_metric_is_rejected_despite_pass_label(tmp_path: Path) -> None:
    scope_path, evidence_path = _write_fixture(tmp_path)
    evidence = json.loads(evidence_path.read_text())
    evidence["comparisons"][0]["status"] = "actual_pass"
    evidence["comparisons"][0]["actual_error_metrics"]["integration_fraction"] = 0.9
    evidence_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")

    verdict = validate_scope_files(scope_path, evidence_path)

    assert verdict["evidence_bound_eligible"] is False
    assert "comparison_error_budget_exceeded" in _codes(verdict)


def test_static_other_family_scope_does_not_require_rigid_body_state(tmp_path: Path) -> None:
    scope_path, evidence_path = _write_fixture(tmp_path)
    scope = json.loads(scope_path.read_text())
    evidence = json.loads(evidence_path.read_text())
    scope["family_id"] = "F1"
    scope["state_requirements"] = _state_requirements(moving=False)
    evidence["family_id"] = "F1"
    for case in scope["physical_domain"]["cases"]:
        case["mechanism_id"] = "static_obstacle"
    for case in evidence["cases"]:
        case["mechanism_id"] = "static_obstacle"
        report_binding = case["qi"]["evidence_file"]
        report_path = Path(report_binding["path"])
        report = json.loads(report_path.read_text())
        report["family_id"] = "F1"
        report_path.write_text(json.dumps(report, sort_keys=True), encoding="utf-8")
        report_binding["sha256"] = hashlib.sha256(report_path.read_bytes()).hexdigest()
        h5_binding = case["qi"]["source_bindings"][0]
        with h5py.File(h5_binding["path"], "r+") as handle:
            handle["type"][..., 1] = 0
            del handle["rigid_body_state"]
        h5_binding["sha256"] = hashlib.sha256(Path(h5_binding["path"]).read_bytes()).hexdigest()
    for row in evidence["reference_views"]:
        report_binding = row["qi"]["evidence_file"]
        report_path = Path(report_binding["path"])
        report = json.loads(report_path.read_text())
        report["family_id"] = "F1"
        report_path.write_text(json.dumps(report, sort_keys=True), encoding="utf-8")
        report_binding["sha256"] = hashlib.sha256(report_path.read_bytes()).hexdigest()
        h5_binding = row["qi"]["source_bindings"][0]
        with h5py.File(h5_binding["path"], "r+") as handle:
            handle["type"][..., 1] = 0
            del handle["rigid_body_state"]
        h5_binding["sha256"] = hashlib.sha256(Path(h5_binding["path"]).read_bytes()).hexdigest()
    scope_path.write_text(json.dumps(scope, indent=2), encoding="utf-8")
    evidence["scope_binding"]["sha256"] = hashlib.sha256(scope_path.read_bytes()).hexdigest()
    evidence_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")

    verdict = validate_scope_files(scope_path, evidence_path)

    assert verdict["evidence_bound_eligible"] is True


def test_explicit_single_background_scope_is_independent_of_unqualified_background(tmp_path: Path) -> None:
    scope_path, evidence_path = _write_fixture(tmp_path)
    scope = json.loads(scope_path.read_text())
    evidence = json.loads(evidence_path.read_text())
    center_case_id = scope["physical_domain"]["cases"][0]["case_id"]
    scope["physical_domain"]["cases"] = [scope["physical_domain"]["cases"][0]]
    scope["reference_requirements"]["backgrounds"] = ["center_catch"]
    scope["reference_requirements"]["expected_view_count"] = 3
    scope["reference_requirements"]["coverage_mode"] = "single_background_explicit"
    scope["reference_requirements"]["reference_case_ids"] = {"center_catch": center_case_id}
    scope["comparison_requirements"] = [item for item in scope["comparison_requirements"] if item["background"] == "center_catch"]
    evidence["cases"] = [item for item in evidence["cases"] if item["case_id"] == center_case_id]
    evidence["reference_views"] = [item for item in evidence["reference_views"] if item["background"] == "center_catch"]
    evidence["comparisons"] = [item for item in evidence["comparisons"] if item["background"] == "center_catch"]
    scope_path.write_text(json.dumps(scope, indent=2), encoding="utf-8")
    evidence["scope_binding"]["sha256"] = hashlib.sha256(scope_path.read_bytes()).hexdigest()
    evidence_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")

    verdict = validate_scope_files(scope_path, evidence_path)

    assert verdict["evidence_bound_eligible"] is True


def test_tampered_source_bytes_invalidate_the_bound_verdict(tmp_path: Path) -> None:
    scope_path, evidence_path = _write_fixture(tmp_path)
    target = tmp_path / "F2_CENTER_CATCH_P01-coarse.solver.log"
    target.write_bytes(b"tampered after evidence was frozen")

    verdict = validate_scope_files(scope_path, evidence_path)

    assert verdict["evidence_bound_eligible"] is False
    assert "artifact_hash_mismatch" in _codes(verdict)


def test_missing_reference_and_empty_internal_observation_are_fail_closed(tmp_path: Path) -> None:
    scope_path, evidence_path = _write_fixture(tmp_path)
    evidence = json.loads(evidence_path.read_text())
    evidence["reference_views"].pop()
    evidence["comparisons"][0]["observations"]["internal"]["metrics"] = {}
    evidence_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")

    verdict = validate_scope_files(scope_path, evidence_path)

    assert verdict["evidence_bound_eligible"] is False
    assert "reference_matrix_incomplete" in _codes(verdict)
    assert "comparison_observation_metrics_empty" in _codes(verdict)


def test_self_declared_qualified_and_fluid_only_reuse_are_rejected(tmp_path: Path) -> None:
    scope_path, evidence_path = _write_fixture(tmp_path)
    evidence = json.loads(evidence_path.read_text())
    evidence["qualified"] = True
    evidence["reuse"] = {
        "strict_scope_equivalence": True,
        "source_state_coverage": "fluid_only_h5",
        "equivalence_evidence": [],
    }
    evidence_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")

    verdict = validate_scope_files(scope_path, evidence_path)

    assert verdict["evidence_bound_eligible"] is False
    codes = _codes(verdict)
    assert "self_declared_qualification_forbidden" in codes
    assert "reuse_fluid_only_forbidden" in codes
