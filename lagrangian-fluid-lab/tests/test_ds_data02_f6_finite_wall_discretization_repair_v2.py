from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "campaigns/ds-data-02/families/F6/handoff_20261002/rigid_contract_003/dp020_dp0125_cpu_003/finite_wall_discretization_repair_002"


def test_repair_002_is_dp020_only_and_keeps_reference_policy():
    manifest = json.loads((AUDIT / "repair_manifest_002.json").read_text())
    assert manifest["status"] == "pending_cpu_gencase_and_actual_bound_vtk_face_qa"
    assert len(manifest["requests"]) == 2
    assert "DP0125" in manifest["supersedes"]["policy"]
    for item in manifest["requests"]:
        assert "DP020" in item["case_id"]
        assert "DP0125" not in item["case_id"]
        request = json.loads(Path(item["request"]["path"]).read_text())
        assert request["cpu_task_kind"] == "gencase"
        assert request["preflight"]["gpu_launch"] is False
        assert request["repair_scope"]["source_physics_unchanged"] is True
        assert request["repair_scope"]["dp0125_policy"].startswith("reference only")
        assert all("DP0125" not in path for path in request["input_files"])
        assert set(request["input_files"]) == set(request["input_sha256"])


def test_evidence_distinguishes_missing_dp020_and_complete_references():
    evidence = json.loads((AUDIT / "finite_wall_discretization_evidence_002.json").read_text())
    assert evidence["new_repair"]["scope"] == "DP020 only"
    assert evidence["bound_face_comparison"]["simple_free_response_dp020"]["faces"]["y_high"]["count"] == 478
    assert evidence["bound_face_comparison"]["wave_no_contact_dp020"]["faces"]["y_high"]["count"] == 478
    assert evidence["bound_face_comparison"]["simple_dp0125"]["faces"]["y_high"]["count"] == 73728
    assert evidence["bound_face_comparison"]["wave_dp0125"]["faces"]["y_high"]["count"] == 73728
    assert evidence["bound_face_comparison"]["simple_dp025"]["faces"]["y_high"]["count"] == 18528
    assert evidence["bound_face_comparison"]["wave_dp025"]["faces"]["y_high"]["count"] == 18528


def test_repaired_xml_is_additive_and_keeps_frozen_body_contract():
    for xml in sorted((AUDIT / "definitions").glob("*_DP020_FINITE_WALL_REPAIR_002_Def.xml")):
        text = xml.read_text()
        assert text.count("Finite tank +Y explicit lattice face repair") == 1
        assert 'x="2.4" y="1.2" z="1.08"' in text
        assert 'massbody value="128"' in text
        assert 'inertia x="8.53333333333" y="8.53333333333" z="13.6533333333"' in text
        assert 'mk="20"' in text
