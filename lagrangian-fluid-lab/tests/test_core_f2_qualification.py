import json
from pathlib import Path

import h5py
import numpy as np
import pytest

from scripts.core_f2_qualification import (
    CANARY_DP_M,
    DURATION_RANGE_S,
    F2_CATCHMENT_GEOMETRY,
    FULL_WINDOW_S,
    MAXIMUM_EXTENDED_WINDOW_S,
    _closed_face_entry_events,
    _catchment_wall_spec,
    _finite_box_spec,
    body_positions,
    audit_dynamic,
    cup_world_from_body,
    duration_for_q,
    motion_angle,
    observe_dynamic,
    qualification_design,
)


LAB = Path(__file__).resolve().parents[1]
DESIGN = LAB / "campaigns/core-v1/cfd/f2-pour-duration-qualification-design.json"
MATRIX = LAB / "campaigns/core-v1/cfd/f2-pour-duration-qualification-matrix.json"
CARD = LAB / "campaigns/core-v1/cfd/f2-pour-duration-parameter-card.json"
PREPARED = LAB / "campaigns/core-v1/cfd/prepared/F2_pour_duration_dynamic_canary/prepared.json"
JOB = LAB / "campaigns/core-v1/cfd/f2-pour-duration-fullwindow-canary-job.json"
IMPACT = LAB / "campaigns/core-v1/cfd/f2-h0-initial-impact-forensics.json"
H2_V2 = LAB / "campaigns/core-v1/cfd/prepared/F2_H2_mdbc_boundary_repair_canary_v2/prepared.json"
ENVELOPE_REPAIR = LAB / "campaigns/core-v1/cfd/prepared/F2_pour_duration_envelope_repair_canary/prepared.json"
ENVELOPE_REPAIR_JOB = LAB / "campaigns/core-v1/cfd/f2-pour-duration-envelope-repair-canary-job.json"
FORENSICS = LAB / "campaigns/core-v1/cfd/f2-dynamic-canary-forensics.json"
ENTRY_FORENSICS = LAB / "campaigns/core-v1/cfd/f2-moving-cup-entry-forensics.json"
H200_ENTRY_FORENSICS = LAB / "campaigns/core-v1/evidence/f2-ballistic-envelope-h200/moving-cup-entry-forensics.json"
H200_REAUDIT = LAB / "campaigns/core-v1/evidence/f2-ballistic-envelope-h200/full-vector-reaudit.json"
BALLISTIC = LAB / "campaigns/core-v1/cfd/prepared/F2_pour_duration_ballistic_envelope_canary/prepared.json"
BALLISTIC_JOB = LAB / "campaigns/core-v1/cfd/f2-pour-duration-ballistic-envelope-canary-job.json"
ENVELOPE_ANALYSIS = LAB / "campaigns/core-v1/cfd/f2-dynamic-envelope-analysis.json"
MDBC_CLOSED_WALL = LAB / "campaigns/core-v1/cfd/prepared/F2_pour_duration_mdbc_closed_wall_canary/prepared.json"
MDBC_CLOSED_WALL_JOB = LAB / "campaigns/core-v1/cfd/f2-pour-duration-mdbc-closed-wall-canary-job.json"
CATCHMENT_V1 = LAB / "campaigns/core-v1/cfd/prepared/F2_closed_catchment_geometry_canary_v1/prepared.json"
CATCHMENT_V1_JOB = LAB / "campaigns/core-v1/cfd/f2-pour-duration-closed-catchment-canary-001-job.json"
CATCHMENT = LAB / "campaigns/core-v1/cfd/prepared/F2_closed_catchment_geometry_canary_v2/prepared.json"
CATCHMENT_JOB = LAB / "campaigns/core-v1/cfd/f2-pour-duration-closed-catchment-canary-v2-001-job.json"
CATCHMENT_V3 = LAB / "campaigns/core-v1/cfd/prepared/F2_closed_catchment_geometry_canary_v3_floor_contract/prepared.json"
CATCHMENT_FLOOR_FORENSICS = LAB / "campaigns/core-v1/evidence/f2-closed-catchment-v2-h200/floor-contract-forensics-v1.json"
WITHDRAWAL = LAB / "campaigns/core-v1/cfd/f2-pour-duration-qualification-withdrawal.json"
PREPARED_MATRIX = LAB / "campaigns/core-v1/cfd/prepared/F2_pour_duration_qualification_v1/prepared-matrix.json"
MATRIX_JOBS = LAB / "campaigns/core-v1/cfd/f2-pour-duration-qualification-jobs.json"


def test_design_is_one_axis_13_plus_2_and_mass_checked():
    design = json.loads(DESIGN.read_text())
    assert design["cell_count"] == 15
    assert design["spatial_cell_count"] == 13
    assert design["temporal_cell_count"] == 2
    assert design["parameter_axis"]["candidate_range_s"] == list(DURATION_RANGE_S)
    assert duration_for_q(0.0) == 0.5
    assert duration_for_q(1.0) == 1.2
    assert design["fixed_physical_case"]["initial_fluid_height_m"] == 0.33
    assert design["fixed_physical_case"]["unchanged"] is True
    assert design["static_mass_status"]["all_mass_gates_pass"] is True
    assert all(row["static_mass_check"]["mass_rescaling"] is False for row in design["cells"])
    assert all(row["static_mass_check"]["mass_gate_pass"] for row in design["cells"])
    matrix = json.loads(MATRIX.read_text())
    assert matrix["complete"] is True
    assert len(matrix["cells"]) == 15
    assert matrix["execution_status"].startswith("registration_only")
    assert matrix["qualification_claim"] == "none"
    card = json.loads(CARD.read_text())
    assert card["parameter"]["name"] == "rotation_duration_s"
    assert card["event_window"]["registered_initial_window_s"] == FULL_WINDOW_S
    assert card["resource_estimates"]["0.005"]["gpu_peak_mib"] == 6144


def test_dynamic_canary_is_cpu_prepared_and_job_is_unqualified():
    prepared = json.loads(PREPARED.read_text())
    job = json.loads(JOB.read_text())
    assert prepared["preflight_pass"] is True
    assert prepared["config"]["physical_geometry_changed"] is False
    assert prepared["config"]["time_max_s"] == FULL_WINDOW_S
    assert prepared["config"]["maximum_extended_time_s"] == MAXIMUM_EXTENDED_WINDOW_S
    assert prepared["config"]["dp_m"] == CANARY_DP_M
    assert prepared["mass_preflight"]["mass_rescaling"] is False
    assert job["qualification_claim"] == "none"
    assert job["registered_window_s"] == FULL_WINDOW_S
    assert job["maximum_extended_window_s"] == MAXIMUM_EXTENDED_WINDOW_S
    assert job["resources"]["gpu_peak_mib"] == 4096


def test_envelope_repair_candidate_is_separate_and_preserves_physics():
    prepared = json.loads(ENVELOPE_REPAIR.read_text())
    job = json.loads(ENVELOPE_REPAIR_JOB.read_text())
    assert prepared["preflight_pass"] is True
    assert prepared["config"]["stage"] == "repair_canary"
    assert prepared["config"]["repair_candidate_id"] == "computational_envelope_all_faces_canary"
    assert prepared["config"]["physical_geometry_changed"] is False
    assert prepared["config"]["mass_rescaling"] is False
    assert prepared["qualification_claim"].startswith("none;")
    assert job["job_id"] == "f2-pour-duration-envelope-repair-canary-001"
    assert job["qualification_claim"] == "none"
    assert job["physical_geometry_changed"] is False
    assert job["resources"]["gpu_peak_mib"] == 6144
    assert job["superseded_by"] == "f2-pour-duration-ballistic-envelope-canary-001"


def test_dynamic_canary_forensics_separates_domain_mismatch_from_native_loss():
    report = json.loads(FORENSICS.read_text())
    assert report["schema"] == "core.f2.dynamic_canary.forensics.v1"
    assert report["qualification_claim"].startswith("none;")
    assert report["domain_comparison"]["declaration_matches_generated_xml"] is False
    assert report["endpoint_recount"]["generated_domain_endpoint_count_is_zero"] is True
    loss = report["native_identity_loss"]
    assert loss["missing_native_fluid_count"] == 16038
    assert loss["runparts"]["totals"]["NpOutPos"] == 16038
    assert loss["runparts"]["totals"]["NpOutRho"] == 0
    assert loss["runparts"]["totals"]["NpOutMov"] == 0
    assert report["tray_reclassification"]["classification"] == "side_entry_below_open_tray; no_bottom_chord"
    reaudited = report["ownership_recontact_reaudit"]
    assert reaudited["cup_closed_face_entry_count"] == 0
    assert reaudited["cup_open_top_exit_count"] > 0
    assert reaudited["cup_first_closed_face_entry"] is None
    assert reaudited["receiver_closed_face_entry_count"] == 0


def test_moving_cup_entry_forensics_reclassifies_legacy_saved_chords():
    report = json.loads(ENTRY_FORENSICS.read_text())
    assert report["classification"] == "legacy_scalar_interpolation_false_positive"
    assert report["historical_scalar_classifier"]["entry_count"] == 3
    assert report["full_vector_reaudit"]["entry_count"] == 0
    assert all(not event["full_crossing_tangential_inside"]
               for event in report["historical_scalar_classifier"]["events"])
    assert all(event["first_prior_open_top_exit_frame"] is not None
               for event in report["historical_scalar_classifier"]["events"])
    assert report["wall_model"]["main_boundary_particle_shell_span_m"] == 0.0225
    h200 = json.loads(H200_ENTRY_FORENSICS.read_text())
    assert h200["historical_scalar_classifier"]["entry_count"] == 1
    assert h200["full_vector_reaudit"]["entry_count"] == 0
    event = h200["historical_scalar_classifier"]["events"][0]
    assert event["frame_index"] == 117
    assert event["particle_id"] == 357014
    assert event["full_crossing_tangential_inside"] is False
    settled = h200["settled_spill_diagnostic"]
    assert settled["final"]["outside_observation_mass_fraction"] > 0.34
    assert settled["final"]["speed_p95_m_s"] > 6.7
    assert settled["final"]["kinetic_energy_over_initial_potential"] > 2.1
    reaudit = json.loads(H200_REAUDIT.read_text())
    assert reaudit["hard_integrity_pass"] is True
    assert reaudit["hard_checks"]["no_cup_closed_face_entries"] is True
    assert reaudit["event_window_complete"] is False


def test_15_cell_cpu_preparation_and_jobs_are_static_only():
    matrix = json.loads(PREPARED_MATRIX.read_text())
    jobs = json.loads(MATRIX_JOBS.read_text())
    assert matrix["complete"] is True
    assert matrix["qualification_claim"] == "none"
    assert len(matrix["cells"]) == 15
    assert all(row["preflight_pass"] and row["static_quality_pass"] and row["mass_gate_pass"]
               for row in matrix["cells"])
    assert jobs["job_count"] == 15
    assert jobs["qualification_claim"] == "none"
    assert jobs["execution_status"].startswith("prepared_only")
    assert jobs["canary_dependency"] == "f2-pour-duration-fullwindow-canary-001"


def test_ballistic_envelope_candidate_has_explicit_physics_and_cost_basis():
    prepared = json.loads(BALLISTIC.read_text())
    job = json.loads(BALLISTIC_JOB.read_text())
    analysis = json.loads(ENVELOPE_ANALYSIS.read_text())
    domain = prepared["config"]["runtime_domain"]
    assert domain["posmin"] == [-7.2, -4.8, -18.7]
    assert domain["posmax"] == [6.1, 5.5, 2.4]
    assert domain["basis"]["gravity_m_s2"] == -9.81
    assert domain["basis"]["physical_geometry_changed"] is False
    assert domain["basis"]["mass_rescaling"] is False
    assert job["resources"]["gpu_peak_mib"] == 12288
    assert job["qualification_claim"] == "none"
    assert analysis["projection"]["predicted_endpoint_min_m"][2] < -18.0
    assert analysis["finite_margin_first_predicted_crossings"]["zmin"]["delay_s"] < 0.08
    assert analysis["finite_margin_first_predicted_crossings"]["ymax"]["crossing_time_s"] < FULL_WINDOW_S
    assert analysis["cell_cost"]["ballistic_full_window_candidate"]["cells"] > 390_000_000


def test_dynamic_mdbc_candidate_has_verified_normals_and_motion_contract():
    prepared = json.loads(MDBC_CLOSED_WALL.read_text())
    job = json.loads(MDBC_CLOSED_WALL_JOB.read_text())
    assert prepared["preflight_pass"] is True
    assert prepared["config"]["boundary_method"] == 2
    assert prepared["config"]["physical_geometry_changed"] is False
    assert prepared["config"]["mass_rescaling"] is False
    assert prepared["native_initial"]["boundary_particles"] == 319608
    assert prepared["native_initial"]["normal_count"] == 319608
    assert prepared["native_initial"]["zero_boundary_normals"] == 0
    assert prepared["config"]["wall_motion_contract"]["axis_body_and_native_file"] == [0.0, 1.0, 0.0]
    assert prepared["config"]["wall_motion_contract"]["pivot_m"] == [0.0, 0.0, 0.65]
    assert prepared["boundary_recipe"]["normal_construction_layers_vdp"] == -0.5
    assert prepared["boundary_recipe"]["normal_search_distance_h"] == 3.0
    assert prepared["boundary_recipe"]["svshapes"] is True
    definition = next(MDBC_CLOSED_WALL.parent.glob("*_Def.xml"))
    xml = definition.read_text()
    assert '<parameter key="Boundary" value="2" />' in xml
    assert '<normals active="true">' in xml
    assert '<distanceh v="3.0" />' in xml
    assert '<svshapes v="true" />' in xml
    assert job["resources"]["gpu_peak_mib"] == 12288
    assert job["qualification_claim"] == "none"
    assert job["physical_geometry_changed"] is False
    assert job["mass_rescaling"] is False
    assert job["launch_recommendation"].startswith("hold pending root review")


def test_closed_catchment_is_a_new_physical_scope_with_explicit_floor_and_walls():
    prepared = json.loads(CATCHMENT.read_text())
    job = json.loads(CATCHMENT_JOB.read_text())
    config = prepared["config"]
    catchment = config["catchment"]
    assert prepared["preflight_pass"] is True
    assert config["scope_id"] == "F2_closed_catchment_geometry_x_v1"
    assert config["revision_id"] == "F2_closed_catchment_geometry_canary_v2"
    assert config["stage"] == "repair_canary"
    assert config["qualification_only"] is True
    assert config["split"] == "qualification_only"
    assert config["physical_geometry_changed"] is True
    assert config["mass_rescaling"] is False
    assert config["qualification_inheritance"].startswith("none")
    assert config["cup"]["low"] == [0.0, -0.15, 0.65]
    assert config["receiver"]["low"] == [0.45, -0.3, 0.0]
    assert config["tray"]["low"] == [-0.6, -0.55, -0.2]
    assert catchment["low"] == F2_CATCHMENT_GEOMETRY["low"]
    assert catchment["size"] == F2_CATCHMENT_GEOMETRY["size"]
    assert catchment["mkbound"] == 3
    assert catchment["floor_material_mkbound"] == 2
    assert catchment["drawn_faces"] == ["left", "right", "front", "back"]
    assert catchment["closed_faces"] == ["bottom", "left", "right", "front", "back"]
    assert catchment["open_faces"] == ["top"]
    assert catchment["nominal_wall_thickness_m"] == 0.0225
    wall_spec = config["catchment_wall_spec"]
    assert wall_spec["container_interior"] == {
        "xmin": -0.6, "xmax": 2.0, "ymin": -0.55, "ymax": 0.55,
        "zmin": -0.1, "zmax": 0.6000000000000001,
    }
    assert wall_spec["surface_convention"] == "continuous source planes; no inward layer-center shrink"
    assert wall_spec["closed_faces"] == ["left", "right", "front", "back"]
    assert wall_spec["open_faces"] == ["top"]
    assert wall_spec["mkbound"] == 3
    assert wall_spec["floor"]["material_mkbound"] == 2
    assert wall_spec["floor"]["fluid_facing_surface_z_m"] == -0.1
    assert wall_spec["floor"]["nominal_outer_low_z_m"] == -0.2
    assert prepared["catchment_recipe"]["preserved_registered_tray_bottom"] is True
    assert prepared["catchment_preflight"]["passed"] is True
    assert prepared["catchment_preflight"]["material_particle_count"] > 0
    assert prepared["catchment_preflight"]["floor_particle_count"] > 0
    estimate = config["catchment_event_window_estimate"]
    assert estimate["estimate_only"] is True
    assert estimate["nominal_floor_contact_from_simulation_start_s"] == pytest.approx(0.979976214157517)
    assert estimate["conservative_outer_bound_contact_from_simulation_start_s"] == pytest.approx(1.0007639423859147)
    assert estimate["registered_window_s"] == FULL_WINDOW_S
    assert estimate["maximum_extended_window_s"] == MAXIMUM_EXTENDED_WINDOW_S
    observer = config["catchment_observer_candidate"]
    assert observer["status"] == "separate_candidate_not_enabled"
    assert observer["uses_current_legacy_tray_observer"] is False
    assert observer["replaces_current_settled_gate"] is False
    definition = next(CATCHMENT.parent.glob("*_Def.xml"))
    xml = definition.read_text()
    assert '<setmkbound mk="3" />' in xml
    assert '<boxfill>left | right | front | back</boxfill>' in xml
    assert '<boxfill>bottom</boxfill>' in xml
    assert '<size x="2.6000000000000001" y="1.1000000000000001" z="0.80000000000000004" />' in xml
    assert job["job_id"] == "f2-pour-duration-closed-catchment-canary-v2-001"
    assert job["qualification_claim"] == "none"
    assert job["physical_geometry_changed"] is True
    assert job["mass_rescaling"] is False
    assert job["qualification_status"].startswith("candidate-only")
    assert job["qualification_only"] is True
    assert job["split"] == "qualification_only"
    assert job["supersedes_prepared_revision"] == "F2_closed_catchment_geometry_canary_v1"
    assert job["geometry_contract"]["old_tray_bottom_retained"] is True
    assert job["observer_contract"]["legacy_settled_gate_unchanged"] is True
    assert job["observer_contract"]["legacy_spill_mass_retained"] is True
    assert job["resources"] == {"cpu_cores": 2, "ram_mib": 32768, "gpu_peak_mib": 12288, "io_weight": 2}


def test_closed_catchment_v1_evidence_is_preserved():
    prepared = json.loads(CATCHMENT_V1.read_text())
    job = json.loads(CATCHMENT_V1_JOB.read_text())
    assert prepared["config"]["revision_id"] == "F2_closed_catchment_geometry_canary_v1"
    assert prepared["config"]["qualification_only"] is False
    assert job["job_id"] == "f2-pour-duration-closed-catchment-canary-001"
    assert job["qualification_claim"] == "none"


def test_closed_catchment_v3_amends_only_the_floor_contract_and_reaudits_same_product():
    prepared = json.loads(CATCHMENT_V3.read_text())
    source = json.loads(CATCHMENT.read_text())
    forensic = json.loads(CATCHMENT_FLOOR_FORENSICS.read_text())
    config = prepared["config"]
    wall = config["catchment_wall_spec"]
    floor = wall["floor"]

    assert prepared["preflight_pass"] is True
    assert prepared["amendment_id"] == "F2_closed_catchment_floor_contract_v1"
    assert prepared["amended_from_prepared_sha256"] == forensic["source_prepared_sha256"]
    assert prepared["solver_input_bytes_unchanged"] is True
    assert prepared["solver_input_definition_sha256"] == forensic["generated_definition_sha256"]
    assert config["revision_id"] == "F2_closed_catchment_geometry_canary_v3_floor_contract"
    assert config["qualification_claim"].startswith("none;")
    assert wall["container_interior"]["zmin"] == -0.2
    assert wall["container_interior"]["zmax"] == pytest.approx(0.6)
    assert floor["fluid_facing_surface_z_m"] == -0.2
    assert floor["nominal_outer_low_z_m"] == -0.2
    assert floor["solid_slab_thickness_m"] == 0.0
    assert floor["surface_basis"].startswith("source boxfill=bottom")

    assert forensic["source_prepared_sha256"] != forensic["amended_prepared_sha256"]
    assert forensic["old_v2_audit"]["hard_integrity_pass"] is False
    assert forensic["old_v2_audit"]["catchment_floor_endpoint_particle_frames"] == 43916
    assert forensic["old_v2_audit"]["catchment_floor_saved_chord_crossings"] == 43916
    assert forensic["amended_reaudit"]["hard_integrity_pass"] is True
    assert forensic["amended_reaudit"]["trajectory_reused_without_solver_rerun"] is True
    floor_audit = forensic["amended_reaudit"]["catchment_floor_geometry"]
    assert floor_audit["endpoint_particle_frames"] == 0
    assert floor_audit["saved_chord_crossings"] == 0
    assert forensic["amended_reaudit"]["catchment_geometry_declaration"]["fluid_facing_floor_surface_z_m"] == -0.2


def _write_single_particle_trajectory(path, positions):
    times = np.asarray([0.0, 0.5, 1.0], dtype=float)
    positions = np.asarray(positions, dtype=float).reshape(3, 1, 3)
    with h5py.File(path, "w") as handle:
        handle["time"] = times
        handle["position"] = positions
        handle["velocity"] = np.zeros_like(positions, dtype=np.float32)
        handle["density"] = np.full((3, 1), 1000.0, dtype=np.float32)
        handle["valid"] = np.ones((3, 1), dtype=bool)
        handle["mass"] = np.ones((3, 1), dtype=np.float32)
        handle["particle_id"] = np.asarray([0], dtype=np.uint32)


def test_catchment_audit_tracks_open_top_and_rejects_side_floor_and_corner_entries(tmp_path):
    prepared = json.loads(CATCHMENT.read_text())
    prepared["sampling"]["expected_fluid_particles"] = 1
    prepared_path = tmp_path / "prepared.json"
    prepared_path.write_text(json.dumps(prepared))

    opening = tmp_path / "opening.h5"
    _write_single_particle_trajectory(opening, [
        [1.80, 0.0, 0.20], [1.80, 0.0, 0.20], [1.80, 0.0, 0.70],
    ])
    opening_audit = audit_dynamic(prepared_path, opening, observe_dynamic(prepared_path, opening))
    catchment = opening_audit["geometry_audit"]["catchment_world_frame"]
    assert opening_audit["hard_integrity_pass"] is True
    assert catchment["open_top_exit_count"] == 1
    assert catchment["open_top_entry_count"] == 0
    assert opening_audit["hard_checks"]["no_catchment_closed_face_entries"] is True
    assert opening_audit["catchment_geometry_declaration"]["fluid_facing_floor_surface_z_m"] == -0.1
    assert opening_audit["catchment_geometry_declaration"]["nominal_low_m"][2] == -0.2

    side_entry = tmp_path / "side-entry.h5"
    _write_single_particle_trajectory(side_entry, [
        [-0.70, 0.0, 0.20], [-0.59, 0.0, 0.20], [-0.59, 0.0, 0.20],
    ])
    side_audit = audit_dynamic(prepared_path, side_entry, observe_dynamic(prepared_path, side_entry))
    assert side_audit["hard_integrity_pass"] is False
    assert side_audit["hard_checks"]["no_catchment_closed_face_entries"] is False
    assert side_audit["geometry_audit"]["catchment_world_frame"]["first_saved_chord_closed_face_entry"]["events"][0]["face"] == "left"

    floor_entry = tmp_path / "floor-entry.h5"
    _write_single_particle_trajectory(floor_entry, [
        [1.80, 0.0, 0.20], [1.80, 0.0, -0.11], [1.80, 0.0, -0.11],
    ])
    floor_audit = audit_dynamic(prepared_path, floor_entry, observe_dynamic(prepared_path, floor_entry))
    assert floor_audit["hard_integrity_pass"] is False
    assert floor_audit["hard_checks"]["no_catchment_floor_endpoint_penetrations"] is False
    assert floor_audit["hard_checks"]["no_catchment_floor_saved_chord_crossings"] is False

    side_spec = prepared["config"]["catchment_wall_spec"]
    corner_events = _closed_face_entry_events(
        np.asarray([[-0.70, -0.65, 0.20]]), np.asarray([[-0.59, -0.54, 0.20]]),
        side_spec, 1e-8,
    )
    assert {event["face"] for event in corner_events} == {"left", "front"}


def test_original_15_cell_matrix_is_explicitly_withdrawn_without_overwrite():
    record = json.loads(WITHDRAWAL.read_text())
    assert record["status"] == "superseded_unlaunchable"
    assert record["execution_status"] == "withdrawn_before_submission"
    assert record["launch_policy"]["queue"] is False
    assert record["launch_policy"]["submit"] is False
    assert record["preserved_original_bytes"] is True
    assert len(record["original_files"]) == 4


def test_geometry_transform_round_trip():
    points = np.array([[0.1, 0.0, 0.8], [0.2, 0.03, 0.9]])
    transform = cup_world_from_body(-105.0)
    world = (np.column_stack((points, np.ones(len(points)))) @ transform.T)[:, :3]
    assert np.allclose(body_positions(world, transform), points)


def test_observer_requires_geometry_aware_receiver_contact_and_full_window(tmp_path):
    prepared = json.loads(PREPARED.read_text())
    hdf5 = tmp_path / "synthetic.h5"
    times = np.asarray([0.0, 0.5, 1.0, 1.4, 1.6, 2.0, 2.5])
    positions = np.asarray([
        [[0.10, 0.0, 0.80]],
        [[0.10, 0.0, 0.80]],
        [[0.50, 0.0, 0.20]],
        [[0.50, 0.0, 0.20]],
        [[0.50, 0.0, 0.20]],
        [[0.50, 0.0, 0.20]],
        [[0.50, 0.0, 0.20]],
    ], dtype=float)
    with h5py.File(hdf5, "w") as handle:
        handle["time"] = times
        handle["position"] = positions
        handle["velocity"] = np.zeros_like(positions, dtype=np.float32)
        handle["valid"] = np.ones((len(times), 1), dtype=bool)
        handle["mass"] = np.full((len(times), 1), 1.0, dtype=np.float32)
    report = observe_dynamic(PREPARED, hdf5)
    assert report["event_times_s"]["receiver_contact"] == 1.0
    assert report["event_times_s"]["settled"] is not None
    assert report["event_window_complete"] is True
    assert report["qualification_claim"].startswith("none")


def test_dynamic_audit_uses_moving_cup_and_separates_integrity_from_event(tmp_path):
    prepared = json.loads(PREPARED.read_text())
    prepared["sampling"]["expected_fluid_particles"] = 2
    prepared_path = tmp_path / "prepared.json"
    prepared_path.write_text(json.dumps(prepared))
    times = np.asarray([0.0, 0.5, 1.0, 1.4, 1.6, 2.0, 2.5])
    positions = np.zeros((len(times), 2, 3), dtype=float)
    for index, current_time in enumerate(times):
        transform = cup_world_from_body(motion_angle(current_time, prepared["config"]["parameter"]["value"]))
        body_point = np.array([[0.10, 0.0, 0.80, 1.0]])
        positions[index, 0] = (body_point @ transform.T)[0, :3]
        positions[index, 1] = [0.50, 0.0, 0.20]
    hdf5 = tmp_path / "trajectory.h5"
    with h5py.File(hdf5, "w") as handle:
        handle["time"] = times
        handle["position"] = positions
        handle["velocity"] = np.zeros((len(times), 2, 3), dtype=np.float32)
        handle["density"] = np.full((len(times), 2), 1000.0, dtype=np.float32)
        handle["valid"] = np.ones((len(times), 2), dtype=bool)
        handle["mass"] = np.ones((len(times), 2), dtype=np.float32)
        handle["particle_id"] = np.asarray([0, 1], dtype=np.uint32)
    observations = observe_dynamic(prepared_path, hdf5)
    audit = audit_dynamic(prepared_path, hdf5, observations)
    assert audit["schema"] == "core.f2.dynamic_audit.v1"
    assert audit["geometry_semantics"]["cup"].startswith("moving finite box")
    assert audit["geometry_semantics"]["receiver"].startswith("fixed finite box")
    assert audit["geometry_semantics"]["tray"].startswith("fixed finite bottom slab")
    assert audit["hard_integrity_pass"] is True
    assert audit["event_window"]["event_window_complete"] is True
    assert audit["hard_checks"]["no_missing_native_fluid_ids"] is True


def test_dynamic_audit_does_not_make_short_window_a_hard_integrity_failure(tmp_path):
    prepared = json.loads(PREPARED.read_text())
    prepared["sampling"]["expected_fluid_particles"] = 2
    prepared_path = tmp_path / "prepared.json"
    prepared_path.write_text(json.dumps(prepared))
    hdf5 = tmp_path / "short-trajectory.h5"
    times = np.asarray([0.0, 0.5])
    positions = np.asarray([
        [[0.10, 0.0, 0.80], [0.50, 0.0, 0.20]],
        [[0.10, 0.0, 0.80], [0.50, 0.0, 0.20]],
    ], dtype=float)
    with h5py.File(hdf5, "w") as handle:
        handle["time"] = times
        handle["position"] = positions
        handle["velocity"] = np.zeros_like(positions, dtype=np.float32)
        handle["density"] = np.full((len(times), 2), 1000.0, dtype=np.float32)
        handle["valid"] = np.ones((len(times), 2), dtype=bool)
        handle["mass"] = np.ones((len(times), 2), dtype=np.float32)
        handle["particle_id"] = np.asarray([0, 1], dtype=np.uint32)
    observations = observe_dynamic(prepared_path, hdf5)
    audit = audit_dynamic(prepared_path, hdf5, observations)
    assert audit["hard_integrity_pass"] is True
    assert audit["window_checks"]["requested_horizon_reached"] is False
    assert audit["event_window_complete"] is False


def test_dynamic_audit_catches_closed_face_in_moving_cup(tmp_path):
    prepared = json.loads(PREPARED.read_text())
    prepared["sampling"]["expected_fluid_particles"] = 1
    prepared_path = tmp_path / "prepared.json"
    prepared_path.write_text(json.dumps(prepared))
    times = np.asarray([0.0, 0.5, 1.0])
    positions = np.zeros((len(times), 1, 3), dtype=float)
    for index, current_time in enumerate(times):
        body_point = np.array([[0.10, 0.0, 0.80, 1.0]])
        transform = cup_world_from_body(motion_angle(current_time, prepared["config"]["parameter"]["value"]))
        positions[index, 0] = (body_point @ transform.T)[0, :3]
    final_transform = cup_world_from_body(motion_angle(times[-1], prepared["config"]["parameter"]["value"]))
    positions[-1, 0] = (np.array([[0.50, 0.0, 0.80, 1.0]]) @ final_transform.T)[0, :3]
    hdf5 = tmp_path / "penetrating-trajectory.h5"
    with h5py.File(hdf5, "w") as handle:
        handle["time"] = times
        handle["position"] = positions
        handle["velocity"] = np.zeros_like(positions, dtype=np.float32)
        handle["density"] = np.full((len(times), 1), 1000.0, dtype=np.float32)
        handle["valid"] = np.ones((len(times), 1), dtype=bool)
        handle["mass"] = np.ones((len(times), 1), dtype=np.float32)
        handle["particle_id"] = np.asarray([0], dtype=np.uint32)
    observations = observe_dynamic(prepared_path, hdf5)
    audit = audit_dynamic(prepared_path, hdf5, observations)
    assert audit["hard_integrity_pass"] is False
    assert audit["hard_checks"]["no_cup_closed_wall_endpoint_penetrations"] is False
    assert audit["geometry_audit"]["cup_moving_body_frame"]["first_endpoint_violation"]["by_face"]["right"] == 1


def test_dynamic_audit_rejects_external_receiver_side_entry(tmp_path):
    prepared = json.loads(PREPARED.read_text())
    prepared["sampling"]["expected_fluid_particles"] = 1
    prepared_path = tmp_path / "prepared.json"
    prepared_path.write_text(json.dumps(prepared))
    hdf5 = tmp_path / "receiver-side-entry.h5"
    times = np.asarray([0.0, 0.5, 1.0])
    positions = np.asarray([
        [[0.40, 0.0, 0.20]],
        [[0.50, 0.0, 0.20]],
        [[0.50, 0.0, 0.20]],
    ], dtype=float)
    with h5py.File(hdf5, "w") as handle:
        handle["time"] = times
        handle["position"] = positions
        handle["velocity"] = np.zeros_like(positions, dtype=np.float32)
        handle["density"] = np.full((len(times), 1), 1000.0, dtype=np.float32)
        handle["valid"] = np.ones((len(times), 1), dtype=bool)
        handle["mass"] = np.ones((len(times), 1), dtype=np.float32)
        handle["particle_id"] = np.asarray([0], dtype=np.uint32)
    audit = audit_dynamic(prepared_path, hdf5, observe_dynamic(prepared_path, hdf5))
    assert audit["hard_integrity_pass"] is False
    assert audit["hard_checks"]["no_receiver_closed_face_entries"] is False
    first_entry = audit["geometry_audit"]["receiver_world_frame"]["first_saved_chord_closed_face_entry"]
    assert first_entry["events"][0]["face"] == "left"


def test_dynamic_audit_rejects_external_moving_cup_side_entry(tmp_path):
    prepared = json.loads(PREPARED.read_text())
    prepared["sampling"]["expected_fluid_particles"] = 1
    prepared_path = tmp_path / "prepared.json"
    prepared_path.write_text(json.dumps(prepared))
    hdf5 = tmp_path / "cup-side-entry.h5"
    times = np.asarray([0.0, 0.5, 1.0])
    # The identity starts outside the cup's right closed face and then enters
    # through that face.  It is never cup-owned, so only the independent entry
    # audit can detect it.
    positions = np.asarray([
        [[0.50, 0.0, 0.80]],
        [[0.40, 0.0, 0.80]],
        [[0.40, 0.0, 0.80]],
    ], dtype=float)
    with h5py.File(hdf5, "w") as handle:
        handle["time"] = times
        handle["position"] = positions
        handle["velocity"] = np.zeros_like(positions, dtype=np.float32)
        handle["density"] = np.full((len(times), 1), 1000.0, dtype=np.float32)
        handle["valid"] = np.ones((len(times), 1), dtype=bool)
        handle["mass"] = np.ones((len(times), 1), dtype=np.float32)
        handle["particle_id"] = np.asarray([0], dtype=np.uint32)
    audit = audit_dynamic(prepared_path, hdf5, observe_dynamic(prepared_path, hdf5))
    assert audit["hard_integrity_pass"] is False
    assert audit["hard_checks"]["no_cup_closed_face_entries"] is False
    first_entry = audit["geometry_audit"]["cup_moving_body_frame"]["first_saved_chord_closed_face_entry"]
    assert first_entry["events"][0]["face"] == "right"


def test_closed_face_entry_uses_full_segment_for_tangential_coordinates():
    spec = _finite_box_spec(
        {"low": [0.0, -0.15, 0.65], "size": [0.425, 0.30, 0.45]},
        ("bottom", "left", "right", "front", "back"),
        ("top",),
    )
    # The scalar normal displacement crosses x=0, but the complete saved
    # segment stays below the front face.  It must not be called a cup entry.
    previous = np.asarray([[-0.04, -0.187, 0.908]])
    current = np.asarray([[0.001, -0.187, 0.902]])
    assert _closed_face_entry_events(previous, current, spec, 1e-8) == []

    # A true left-face entry with the same x motion and a tangentially valid
    # segment remains detectable.
    previous = np.asarray([[-0.04, -0.14, 0.908]])
    current = np.asarray([[0.001, -0.14, 0.902]])
    events = _closed_face_entry_events(previous, current, spec, 1e-8)
    assert len(events) == 1
    assert events[0]["face"] == "left"


def test_dynamic_audit_retracks_cup_after_open_top_reentry(tmp_path):
    prepared = json.loads(PREPARED.read_text())
    prepared["sampling"]["expected_fluid_particles"] = 1
    prepared_path = tmp_path / "prepared.json"
    prepared_path.write_text(json.dumps(prepared))
    times = np.asarray([0.0, 0.5, 1.0, 1.4])
    body_points = np.asarray([
        [0.10, 0.0, 0.80],
        [0.10, 0.0, 1.20],
        [0.10, 0.0, 0.80],
        [0.50, 0.0, 0.80],
    ])
    positions = np.zeros((len(times), 1, 3), dtype=float)
    for index, current_time in enumerate(times):
        body = np.column_stack((body_points[index:index + 1], np.ones(1)))
        transform = cup_world_from_body(motion_angle(current_time, prepared["config"]["parameter"]["value"]))
        positions[index, 0] = (body @ transform.T)[0, :3]
    hdf5 = tmp_path / "cup-reentry.h5"
    with h5py.File(hdf5, "w") as handle:
        handle["time"] = times
        handle["position"] = positions
        handle["velocity"] = np.zeros_like(positions, dtype=np.float32)
        handle["density"] = np.full((len(times), 1), 1000.0, dtype=np.float32)
        handle["valid"] = np.ones((len(times), 1), dtype=bool)
        handle["mass"] = np.ones((len(times), 1), dtype=np.float32)
        handle["particle_id"] = np.asarray([0], dtype=np.uint32)
    audit = audit_dynamic(prepared_path, hdf5, observe_dynamic(prepared_path, hdf5))
    cup = audit["geometry_audit"]["cup_moving_body_frame"]
    assert cup["open_top_exit_count"] == 1
    assert cup["open_top_entry_count"] == 1
    assert audit["hard_checks"]["no_cup_closed_wall_endpoint_penetrations"] is False


def test_dynamic_audit_does_not_call_tray_bottom_penetration_for_side_entry_below_open_slab(tmp_path):
    prepared = json.loads(PREPARED.read_text())
    prepared["sampling"]["expected_fluid_particles"] = 1
    prepared_path = tmp_path / "prepared.json"
    prepared_path.write_text(json.dumps(prepared))
    hdf5 = tmp_path / "tray-side-entry.h5"
    times = np.asarray([0.0, 0.5, 1.0])
    positions = np.asarray([
        [[0.0, -0.60, 0.0]],
        [[0.0, -0.60, -0.22]],
        [[0.0, -0.54, -0.30]],
    ], dtype=float)
    with h5py.File(hdf5, "w") as handle:
        handle["time"] = times
        handle["position"] = positions
        handle["velocity"] = np.zeros_like(positions, dtype=np.float32)
        handle["density"] = np.full((len(times), 1), 1000.0, dtype=np.float32)
        handle["valid"] = np.ones((len(times), 1), dtype=bool)
        handle["mass"] = np.ones((len(times), 1), dtype=np.float32)
        handle["particle_id"] = np.asarray([0], dtype=np.uint32)
    audit = audit_dynamic(prepared_path, hdf5, observe_dynamic(prepared_path, hdf5))
    tray = audit["geometry_audit"]["tray_world_frame"]
    assert tray["endpoint_particle_frames"] == 0
    assert tray["saved_chord_crossings"] == 0


def test_initial_impact_forensics_and_h2_v2_evidence_are_retained():
    impact = json.loads(IMPACT.read_text())
    assert impact["initial_condition"]["initial_velocity_max_m_s"] == 0.0
    assert impact["initial_condition"]["clearance_to_physical_cup_faces_m"]["bottom"] == 0.05500000000000005
    assert impact["initial_condition"]["initial_potential_energy_relative_to_cup_floor_J"] > 51.0
    assert impact["observed_impact"]["peak_saved_max_vz_m_s"] > 6.0
    assert impact["interpretation"]["resting_fill_status"].startswith("would require")
    h2 = json.loads(H2_V2.read_text())
    assert h2["preflight_pass"] is True
    assert h2["native_initial"]["normal_count"] == h2["native_initial"]["boundary_particles"]
    assert h2["native_initial"]["zero_boundary_normals"] == 0
    definition = next(path for path in (H2_V2.parent).glob("*_Def.xml"))
    xml = definition.read_text()
    assert 'layers vdp="-0.5"' in xml
    assert '<distanceh v="3.0" />' in xml
