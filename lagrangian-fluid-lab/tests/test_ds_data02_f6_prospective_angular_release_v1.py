#!/usr/bin/env python3
"""Tests for F6 prospective full 3D free 6DOF angular release candidate and descriptive analysis."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import pytest

WORKTREE_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics")
F6_DIR = WORKTREE_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003"
PROSPECTIVE_DIR = F6_DIR / "prospective_angular_release_001"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def test_source_code_angvelini_verification():
    """Verify official DualSPHysics source implements angularvelini in rad/s and rigid node propagation."""
    jcaseparts = WORKTREE_ROOT / "src/source/JCaseParts.cpp"
    assert jcaseparts.is_file()
    content = jcaseparts.read_text(encoding="utf-8")
    assert 'AngularVelini=sxml->ReadElementDouble3(ele,(sxml->ExistsElement(ele,"angularvelini")? "angularvelini": "omegaini"),true);' in content
    assert 'sxml->AddElementDouble3(ele,"angularvelini",AngularVelini),"units_comment","rad/s"' in content

    jsph = WORKTREE_ROOT / "src/source/JSph.cpp"
    assert jsph.is_file()
    jsph_content = jsph.read_text(encoding="utf-8")
    assert "fobj->fomega=ToTFloat3(fblock.GetAngularVelini());" in jsph_content

    # Verify node velocity propagation v_r = v_lin + omega x (r - r_c)
    cpu_single = WORKTREE_ROOT / "src/source/JSphCpuSingle.cpp"
    assert cpu_single.is_file()
    cpu_content = cpu_single.read_text(encoding="utf-8")
    assert "vr.x=fvel.x+(fomega.y*dist.z - fomega.z*dist.y);" in cpu_content
    assert "vr.y=fvel.y+(fomega.z*dist.x - fomega.x*dist.z);" in cpu_content
    assert "vr.z=fvel.z+(fomega.x*dist.y - fomega.y*dist.x);" in cpu_content

    gpu_ker = WORKTREE_ROOT / "src/source/JSphGpu_ker.cu"
    assert gpu_ker.is_file()
    gpu_content = gpu_ker.read_text(encoding="utf-8")
    assert "vr.x=fvel.x+(fomega.y*distz - fomega.z*disty);" in gpu_content
    assert "vr.y=fvel.y+(fomega.z*distx - fomega.x*distz);" in gpu_content
    assert "vr.z=fvel.z+(fomega.x*disty - fomega.y*distx);" in gpu_content


def test_prospective_case_definitions():
    """Verify coarse, medium, fine XML case definitions match physical contract."""
    cases = {
        "coarse": (PROSPECTIVE_DIR / "cases/coarse/F6_ANGULAR_RELEASE_DP025_Def.xml", 0.025),
        "medium": (PROSPECTIVE_DIR / "cases/medium/F6_ANGULAR_RELEASE_DP020_Def.xml", 0.020),
        "fine": (PROSPECTIVE_DIR / "cases/fine/F6_ANGULAR_RELEASE_DP0125_Def.xml", 0.0125),
    }

    for role, (xml_path, expected_dp) in cases.items():
        assert xml_path.is_file(), f"Missing {xml_path}"
        tree = ET.parse(xml_path)
        root = tree.getroot()

        # Check definition DP
        geom_def = root.find("./casedef/geometry/definition")
        assert geom_def is not None
        assert float(geom_def.get("dp")) == pytest.approx(expected_dp)

        # Check floating body definition
        floating = root.find("./casedef/floatings/floating[@mkbound='50']")
        assert floating is not None

        massbody = floating.find("massbody")
        assert float(massbody.get("value")) == 128.0

        center = floating.find("center")
        assert [float(center.get(a)) for a in "xyz"] == [2.4, 1.2, 1.08]

        inertia = floating.find("inertia")
        assert float(inertia.get("x")) == pytest.approx(8.53333333333)
        assert float(inertia.get("y")) == pytest.approx(8.53333333333)
        assert float(inertia.get("z")) == pytest.approx(13.6533333333)

        trans_dof = floating.find("translationDOF")
        assert [int(trans_dof.get(a)) for a in "xyz"] == [1, 1, 1]

        rot_dof = floating.find("rotationDOF")
        assert [int(rot_dof.get(a)) for a in "xyz"] == [1, 1, 1]

        angvelini = floating.find("angularvelini")
        assert angvelini is not None
        assert [float(angvelini.get(a)) for a in "xyz"] == [0.08, 0.12, 0.06]

        # Check parameters
        params = {p.get("key"): p.get("value") for p in root.findall("./execution/parameters/parameter")}
        assert params["ViscoTreatment"] == "2"
        assert float(params["Visco"]) == pytest.approx(1e-6)
        assert float(params["TimeMax"]) == 12.0
        assert float(params["TimeOut"]) == 0.05


def test_preregistration_and_manifest():
    """Verify preregistration.json and manifest.json schemas, hashes, and authority boundaries."""
    prereg_file = PROSPECTIVE_DIR / "preregistration.json"
    manifest_file = PROSPECTIVE_DIR / "manifest.json"

    assert prereg_file.is_file()
    assert manifest_file.is_file()

    prereg = json.loads(prereg_file.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))

    assert prereg["schema"] == "ds02.f6.prospective-preregistration.v1"
    assert prereg["scope_classification"] == "new_physical_control_scope"
    assert prereg["is_body_cellcenter_repair"] is False
    assert prereg["negative_reference_preservation"]["zero_spin_retained_as_negative_evidence"] is True
    assert prereg["status"]["launch_allowed"] is False
    assert prereg["status"]["q_n_status"] == "not_assessed"

    assert manifest["schema"] == "ds02.f6.prospective-manifest.v1"
    assert manifest["launch_allowed"] is False
    assert manifest["preregistration"]["sha256"] == sha256(prereg_file)

    for role in ("coarse", "medium", "fine"):
        case_info = manifest["cases"][role]
        def_xml = Path(case_info["def_xml"])
        req_json = Path(case_info["request"])
        assert def_xml.is_file()
        assert req_json.is_file()
        assert case_info["def_xml_sha256"] == sha256(def_xml)
        assert case_info["request_sha256"] == sha256(req_json)

        # Check request contents
        req = json.loads(req_json.read_text(encoding="utf-8"))
        assert req["launch_allowed"] is False
        assert req["root_review_required"] is True
        assert req["cpu_threads"] <= 2
        assert req["max_wall_seconds"] <= 3600


def test_existing_floating_descriptive_analysis_receipt_and_results():
    """Verify descriptive analysis executed cleanly under strictguard and produced valid findings."""
    attempt_dir = DATA_ROOT / "families/F6/F6_BODY_CELLCENTER_DESCRIPTIVE_ANALYSIS/f6-existing-floating-descriptive-analysis-002"
    receipt_file = attempt_dir / "execution-receipt.json"
    analysis_file = attempt_dir / "existing-floating-descriptive-analysis.json"

    assert receipt_file.is_file(), f"Receipt missing: {receipt_file}"
    assert analysis_file.is_file(), f"Analysis missing: {analysis_file}"

    receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
    assert receipt["status"] == "completed"
    assert receipt["returncode"] == 0

    analysis = json.loads(analysis_file.read_text(encoding="utf-8"))
    assert analysis["schema"] == "ds02.f6.floating-descriptive-analysis.v1"

    # Verify peak angular amplitudes in radians
    res = analysis["resolutions"]
    for role in ("coarse", "medium", "fine"):
        data = res[role]
        assert data["frames"] == 241
        peaks = data["peak_angular_amplitudes_rad"]
        assert all(0.0 <= peaks[k] < 0.15 for k in ("roll", "pitch", "yaw"))
        assert data["initial_angular_velocity_rad_s"] == {"wx": 0.0, "wy": 0.0, "wz": 0.0}

    # Verify separate absolute and relative RMSE
    pairwise = analysis["pairwise_comparisons"]
    for pair_name, pair_data in pairwise.items():
        ori = pair_data["orientation_euler_rad"]
        assert "absolute_rmse" in ori
        assert "relative_rmse_to_reference_peak" in ori
        # Absolute RMSE is small (under 0.07 rad)
        assert all(rmse < 0.07 for rmse in ori["absolute_rmse"])

    # Verify conditioning diagnosis exists and preserves 5% macro operator
    cond = analysis["conditioning_diagnosis"]
    assert cond["frozen_macro_metric_preserved"] is True
    assert cond["new_gate_introduced"] is False
