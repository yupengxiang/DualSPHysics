from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "campaigns/ds-data-02/families/F6/handoff_20261002/rigid_contract_003/dp020_dp0125_cpu_003/finite_wall_discretization_repair_001"


def test_root_cause_face_counts_and_failed_particles_are_recorded() -> None:
    evidence = json.loads((AUDIT / "finite_wall_discretization_evidence_001.json").read_text())
    simple = evidence["bound_face_comparison"]["simple_free_response_dp020"]
    wave = evidence["bound_face_comparison"]["wave_no_contact_dp020"]
    for row in (simple, wave):
        assert row["fixed_points"] == 85682
        assert row["faces"]["x_low"]["count"] == 14400
        assert row["faces"]["x_high"]["count"] == 14400
        assert row["faces"]["y_low"]["count"] == 28800
        assert row["faces"]["y_high"]["count"] == 478
        assert row["faces"]["z_low"]["count"] == 28800
    assert evidence["failed_solver_evidence"]["simple_free_response_dp020"]["error"]["idp"] == 120962
    assert evidence["failed_solver_evidence"]["simple_free_response_dp020"]["error"]["type"] == 2
    assert evidence["failed_solver_evidence"]["wave_no_contact_dp020"]["error"]["idp"] == 199046
    assert evidence["failed_solver_evidence"]["wave_no_contact_dp020"]["error"]["type"] == 2


def test_comparison_resolutions_have_full_high_y_face() -> None:
    evidence = json.loads((AUDIT / "finite_wall_discretization_evidence_001.json").read_text())
    assert evidence["bound_face_comparison"]["simple_dp0125"]["faces"]["y_high"]["count"] == 73728
    assert evidence["bound_face_comparison"]["wave_dp0125"]["faces"]["y_high"]["count"] == 73728
    assert evidence["bound_face_comparison"]["simple_dp025"]["faces"]["y_high"]["count"] == 18528
    assert evidence["bound_face_comparison"]["wave_dp025"]["faces"]["y_high"]["count"] == 18528


def test_new_requests_are_cpu_only_and_source_bound() -> None:
    manifest = json.loads((AUDIT / "repair_manifest_001.json").read_text())
    assert manifest["gpu_launch"] is False
    assert manifest["status"] == "pending_cpu_gencase_and_actual_bound_vtk_face_qa"
    requests = sorted((AUDIT / "gencase_requests").glob("*.json"))
    assert len(requests) == 4
    for path in requests:
        request = json.loads(path.read_text())
        assert request["cpu_task_kind"] == "gencase"
        assert request["kind"] == "cpu"
        assert request["command"][0].endswith("/GenCase_linux64")
        assert request["command"][-1] == "-save:all"
        assert request["preflight"]["gpu_launch"] is False
        assert len(request["input_files"]) == len(request["input_sha256"])
        xml = Path(request["command"][1] + ".xml")
        assert "Finite tank +Y explicit lattice face repair" in xml.read_text()
