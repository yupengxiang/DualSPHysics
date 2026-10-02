from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "campaigns/ds-data-02/families/F6/handoff_20261002/rigid_contract_003/dp020_dp0125_cpu_003/finite_wall_discretization_repair_002"


def test_actual_native_repair_002_contract_and_five_face_qa_pass():
    report = json.loads((AUDIT / "native_audit_001.json").read_text())
    assert report["status"] == "both_repair_002_native_preflight_pass"
    assert report["gpu_launch"] is False
    assert len(report["cases"]) == 2
    for row in report["cases"]:
        assert row["preflight_pass"] is True
        assert row["checks"]["actual_3d"] is True
        assert row["checks"]["fluid_count_receipt_640000"] is True
        assert row["checks"]["fluid_mass_5120kg"] is True
        assert row["checks"]["body_128kg_center_inertia"] is True
        assert row["checks"]["fixed_five_physical_faces_covered"] is True
        assert row["native_boundary"]["type_counts"]["0"] == 114004
        assert row["native_boundary"]["type_counts"]["2"] == 35301
        expected_moving = 77408 if row["mechanism_id"] == "wave_no_contact" else 0
        assert row["native_boundary"]["type_counts"].get("1", 0) == expected_moving
        assert row["native_boundary"]["fixed_boundary_face_coverage"]["faces"]["y_high"]["native_near_plane_points"] == 28800
        assert row["native_xml_contract"]["type2_particle_mass_kg"] != 128.0
        assert row["native_xml_contract"]["type2_particle_mass_policy"].startswith("separate")


def test_domain_stage_changes_only_generated_simulation_domain():
    stage = json.loads((AUDIT / "solver_domain_stage_001.json").read_text())
    assert stage["physical_geometry_unchanged"] is True
    assert stage["source_native_files_byte_identical_except_generated_xml"] is True
    assert stage["domain_low_m"] == [-0.25, -0.15, -0.15]
    assert stage["domain_high_m"] == [5.1, 2.55, 3.05]
    for row in stage["cases"]:
        assert len(row["files"]) == 7
        xml = next(item for item in row["files"] if item["name"] == "xml")
        assert xml["change"]["only"].startswith("execution.parameters.simulationdomain")
        assert xml["change"]["staged_numeric"]["posmin"] == [-0.25, -0.15, -0.15]


def test_solver_requests_are_root_only_full_window_and_hash_bound():
    manifest = json.loads((AUDIT / "solver_requests_001/request_manifest.json").read_text())
    assert manifest["status"] == "root_dispatch_pending"
    assert manifest["gpu_launch"] is False
    assert len(manifest["requests"]) == 2
    for row in manifest["requests"]:
        request = json.loads(Path(row["path"]).read_text())
        assert request["kind"] == "qualification"
        assert request["command"][-2:] == ["-tmax:12", "-tout:0.05"]
        assert request["complete_event_window_s"] == [0.0, 12.0]
        assert request["output_interval_s"] == 0.05
        assert request["qualification_claim"].startswith("none")
        assert request["launch_authority"].startswith("root only")
        assert request["runtime_prefix_contract"]["all_xml_references_resolve_from_prefix"] is True
        assert request["runtime_prefix_contract"]["source_native_files_byte_identical_except_domain_xml"] is True
        assert request["runtime_prefix_contract"]["simulationdomain_low_m"] == [-0.25, -0.15, -0.15]
        assert request["runtime_prefix_contract"]["simulationdomain_high_m"] == [5.1, 2.55, 3.05]
        assert set(request["input_files"]) == set(request["input_sha256"])
        assert all(Path(path).is_file() for path in request["input_files"])
        assert request["estimated_storage_bytes"] >= 16 * 1024**3
