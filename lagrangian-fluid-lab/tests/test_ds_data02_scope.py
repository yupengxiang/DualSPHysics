from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from scripts.ds_data02_scope import (
    CURRENT_EVIDENCE_CLASS,
    FULL_STATE_COVERAGE,
    REQUIRED_TYPED_DATASETS,
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
        "recipe": _recipe(),
        "time_domain": {"start_s": 0.0, "end_s": 4.0, "complete_event_window": True, "minimum_frames": 4},
        "observations": _observations(),
        "physical_domain": {"cases": cases},
        "reference_requirements": {
            "backgrounds": ["center_catch", "offset_spill"],
            "resolutions": ["coarse", "medium", "fine"],
            "expected_view_count": 6,
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


def _qi(root: Path, case: dict[str, object]) -> dict[str, object]:
    return {
        "evidence_class": CURRENT_EVIDENCE_CLASS,
        "state_coverage": FULL_STATE_COVERAGE,
        "status": "Q-I-structure-pass",
        "resolution": case["qi_resolution"],
        "evidence_file": _binding(root, f"{case['case_id']}-qi.json", "qi_report", {"status": "Q-I-structure-pass"}),
        "source_bindings": [_binding(root, f"{case['case_id']}-trajectory.h5", "trajectory_h5", b"FULL_TYPED_H5")],
        "solver_dimension": 3,
        "coordinate_components": 3,
        "fluid_count": 100,
        "active_mass_kg": 1.5,
        "checks": {
            "solver_log_explicit_3d": True,
            "nonzero_fluid": True,
            "positive_active_mass": True,
            "time_axis": True,
            "active_state_finite": True,
            "typed_ids": True,
            "moving_boundary_pose": True,
            "boundary_mass_separated": True,
            "event_ids_typed": True,
            "physical_spill_separated_from_unknown": True,
        },
        "full_timeline": {"complete": True, "frames": 401, "start_s": 0.0, "end_s": 4.0, "time_axis_strictly_increasing": True},
        "typed_identity": {"axis": "(Zone,Idp)", "datasets": sorted(REQUIRED_TYPED_DATASETS), "introduced_count": 0, "revived_count": 0, "type_changed_count": 0},
        "moving_boundary": {"node_count": 10, "pose_saved": True, "control_bound": True, "position_rms_max_m": 1e-8},
        "mass_audit": {"initial_fluid_mass_kg": 1.5, "boundary_mass_separated": True, "unknown_separate_from_spill": True},
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
    scope_hash = hashlib.sha256(scope_path.read_bytes()).hexdigest()
    equivalence = _binding(tmp_path, "reuse-equivalence.json", "scope_equivalence_report", {"equivalent": True})
    evidence["reuse"] = {
        "strict_scope_equivalence": True,
        "source_state_coverage": FULL_STATE_COVERAGE,
        "scope_id": scope["scope_id"],
        "scope_sha256": scope_hash,
        "recipe": _recipe(),
        "time_domain": scope["time_domain"],
        "physical_case_ids": [case["case_id"] for case in scope["physical_domain"]["cases"]],
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
