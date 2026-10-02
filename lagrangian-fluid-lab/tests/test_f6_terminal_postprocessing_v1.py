"""Static guards for the additive F6 terminal evidence/request bundle."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FAMILY = ROOT / "campaigns/ds-data-02/families/F6/handoff_20261002/rigid_contract_003"
AUDIT = FAMILY / "dp0125_finite_face_reference_001/finite_face_audit_001.json"
DP0125_MANIFEST = FAMILY / "dp0125_finite_face_reference_001/solver_requests_001/request_manifest.json"
DP020_MANIFEST = FAMILY / "dp020_repair_002_postprocessing_001/execution_requests/request_manifest.json"


def _read(path: Path) -> dict:
    assert path.is_file(), path
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_dp0125_native_face_audit_is_explicit_and_passes():
    payload = _read(AUDIT)
    assert payload["helper"]["sha256"] == "16bd1e8d0883a9307bcb54a0d5395acf83bdefb6de1a97ae44706fc3aa2105e1"
    assert payload["all_cases_finite_faces_pass"] is True
    for case in payload["cases"]:
        assert case["audit_pass"] is True
        assert case["actual_3d"] is True
        assert case["fluid_mass_contract"]["actual_xml_fluid_mass_kg"] == 5120.0
        assert case["rigid_contract"]["aggregate_massbody_kg"] == 128.0
        assert case["finite_face_audit"]["all_five_finite_faces_covered"] is True
        assert "z_high" not in case["finite_face_audit"]["faces"]


def test_dp0125_requests_keep_domain_review_pending():
    payload = _read(DP0125_MANIFEST)
    assert payload["qualification_claim"] == "none"
    assert payload["gpu_launch"] is False
    for row in payload["requests"]:
        request = _read(Path(row["path"]))
        assert request["launch_authority"].startswith("root only")
        assert request["simulationdomain_gate"]["status"] == "pending_root_domain_review"
        assert request["finite_wall_contract"]["native_face_gate"] == "pass"
        assert request["gencase_actual_particles"]["fluid"] == 2621440
        assert request["native_initial_mass_contract"]["fluid_mass_kg"] == 5120.0
        assert request["qualification_claim"].startswith("none")


def test_dp020_postprocessing_is_cpu_only_and_records_unknown_position_loss():
    payload = _read(DP020_MANIFEST)
    assert payload["gpu_launch"] is False
    assert payload["solver_launch"] is False
    assert len(payload["audits"]) == 2
    for row in payload["audits"]:
        audit = _read(Path(row["audit"]))
        assert audit["checks"]["terminal_code0"] is True
        assert audit["checks"]["full_12s"] is True
        assert audit["checks"]["241_frames"] is True
        assert audit["native_exclusion"]["sums"] == {"NpOut": 1, "NpOutPos": 1, "NpOutRho": 0, "NpOutMov": 0}
        assert "unknown" in audit["native_exclusion"]["unknown_position_exclusion_policy"]
    for row in payload["requests"]:
        request = _read(Path(row["path"]))
        assert request["gpu_launch"] is False
        assert request["qualification_claim"] == "none; postprocessing evidence only"
        assert request["rigid_contract"]["type2_particle_mass_is_separate_from_aggregate_massbody"] is True
