"""Synthetic unit tests for F3 True Adaptive Spatial Ladder Preparation (Round 030)."""

import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

HANDOFF_DIR = (
    Path(__file__).resolve().parents[1]
    / "campaigns"
    / "ds-data-02"
    / "families"
    / "F3"
    / "handoff_20261003"
    / "root_true_adaptive_spatial_ladder_030"
)


def test_physical_mother_continuum_conservation():
    """Verify mother continuum fluid geometry and mass conservation across resolutions."""
    lx, ly, lz = 0.9, 0.18, 0.51
    depth = 0.09
    rhop0 = 1000.0
    v_continuum = lx * ly * depth
    m_continuum = rhop0 * v_continuum
    assert abs(v_continuum - 0.01458) < 1e-12
    assert abs(m_continuum - 14.58) < 1e-12

    for dp, expected_fluid in [(0.015, 4320), (0.010, 14580), (0.0075, 34560)]:
        nx = lx / dp
        ny = ly / dp
        nz = depth / dp
        assert abs(nx - round(nx)) < 1e-9 and abs(ny - round(ny)) < 1e-9 and abs(nz - round(nz)) < 1e-9
        fluid_particles = int(round(nx)) * int(round(ny)) * int(round(nz))
        assert fluid_particles == expected_fluid
        particle_mass = rhop0 * (dp ** 3)
        fluid_mass = fluid_particles * particle_mass
        assert abs(fluid_mass - m_continuum) < 1e-6


def test_commensurate_triad_integer_ratios():
    """Verify commensurate grid spacing ratios across Coarse, Medium, and Fine."""
    dp_coarse = 0.015
    dp_medium = 0.010
    dp_fine = 0.0075

    assert abs(dp_coarse / dp_fine - 2.0) < 1e-12
    assert abs(dp_medium / dp_fine - 4.0 / 3.0) < 1e-12
    assert abs(dp_coarse / dp_medium - 1.5) < 1e-12

    # Integer grid alignment: every 2 coarse cells = 3 medium cells = 4 fine cells (0.030m)
    common_cell_span = 0.030
    assert abs(common_cell_span / dp_coarse - 2.0) < 1e-12
    assert abs(common_cell_span / dp_medium - 3.0) < 1e-12
    assert abs(common_cell_span / dp_fine - 4.0) < 1e-12


def test_xml_definition_files_exist_and_parse():
    """Verify that all 3 XML definition files exist, parse, and conform to CELL3 geometry."""
    def_dir = HANDOFF_DIR / "definitions"
    ladder = [
        ("F3_CELL3_plain_0p015_Def.xml", 0.015, 4320),
        ("F3_CELL3_plain_0p010_Def.xml", 0.010, 14580),
        ("F3_CELL3_plain_0p0075_Def.xml", 0.0075, 34560),
    ]

    for fname, dp, expected_fluid in ladder:
        path = def_dir / fname
        assert path.exists(), f"Missing definition file {path}"
        tree = ET.parse(path)
        root = tree.getroot()

        # Check geometry definition
        geom = root.find(".//geometry/definition")
        assert geom is not None
        assert abs(float(geom.get("dp")) - dp) < 1e-6
        pref = [float(geom.find("pointref").get(k)) for k in ("x", "y", "z")]
        assert all(abs(a - dp / 2.0) < 1e-6 for a in pref)

        # Check mother geometry for normals
        norm_box = root.find(".//list[@name='GeometryForNormals']/drawbox")
        assert norm_box is not None
        p_norm = [float(norm_box.find("point").get(k)) for k in ("x", "y", "z")]
        s_norm = [float(norm_box.find("size").get(k)) for k in ("x", "y", "z")]
        assert p_norm == [-0.45, -0.09, 0.0]
        assert s_norm == [0.9, 0.18, 0.51]

        # Check fluid box
        f_box = root.find(".//mainlist/drawbox[boxfill='solid']")
        assert f_box is not None
        fp = [float(f_box.find("point").get(k)) for k in ("x", "y", "z")]
        fs = [float(f_box.find("size").get(k)) for k in ("x", "y", "z")]
        assert all(abs(a - b) < 1e-5 for a, b in zip(fp, [-0.45 + dp / 2.0, -0.09 + dp / 2.0, dp / 2.0]))
        assert all(abs(a - b) < 1e-5 for a, b in zip(fs, [0.9 - dp, 0.18 - dp, 0.09 - dp]))

        # Check boundary box
        b_box = root.find(".//mainlist/drawbox[layers]")
        assert b_box is not None
        bp = [float(b_box.find("point").get(k)) for k in ("x", "y", "z")]
        bs = [float(b_box.find("size").get(k)) for k in ("x", "y", "z")]
        assert all(abs(a - b) < 1e-5 for a, b in zip(bp, [-0.45 - dp / 2.0, -0.09 - dp / 2.0, -dp / 2.0]))
        assert all(abs(a - b) < 1e-5 for a, b in zip(bs, [0.9 + dp, 0.18 + dp, 0.51 + dp / 2.0]))
        assert b_box.find("layers").get("vdp") == "0,1,2"


def test_numerical_recipe_parity_across_ladder():
    """Verify that all 3 resolutions enforce identical unclamped adaptive numerical recipe."""
    def_dir = HANDOFF_DIR / "definitions"
    for fname in ["F3_CELL3_plain_0p015_Def.xml", "F3_CELL3_plain_0p010_Def.xml", "F3_CELL3_plain_0p0075_Def.xml"]:
        tree = ET.parse(def_dir / fname)
        root = tree.getroot()

        # CFL
        cfl = float(root.find(".//cflnumber").get("value"))
        assert abs(cfl - 0.05) < 1e-6

        # Parameters
        params = {n.get("key"): n.get("value") for n in root.findall(".//parameters/parameter")}
        assert params["CoefDtMin"] == "0.005", "Must use decoupled CoefDtMin 0.005"
        assert params["StepAlgorithm"] == "2", "Must use Symplectic"
        assert params["Kernel"] == "2", "Must use Wendland"
        assert params["ViscoTreatment"] == "1", "Must use Artificial viscosity"
        assert params["Visco"] == "0.05"
        assert params["ViscoBoundFactor"] == "1"
        assert params["DensityDT"] == "3", "Must use Fourtakas full DDT"
        assert params["DensityDTvalue"] == "0.1"
        assert params["Shifting"] == "0", "Must have Shifting disabled"
        assert params["DtIni"] == "0"
        assert params["DtMin"] == "0"
        assert params["DtFixed"] == "0"
        assert params["TimeMax"] == "8.35"
        assert params["TimeOut"] == "0.01"
        assert params["NoPenetration"] == "1"
        assert params["Boundary"] == "2", "Must use mDBC"
        assert params["SlipMode"] == "2", "Must use No-slip"
        assert params["SavePosDouble"] == "2"

        # Acc input
        acc = root.find(".//accinput")
        assert acc.find("acctimesfile").get("value") == "CaseSloshingAccData.csv"
        assert acc.find("globalgravity").get("value") == "0"
        centre = [float(acc.find("acccentre").get(k)) for k in ("x", "y", "z")]
        assert centre == [0.45, 0.0, 0.0]


def test_prohibition_on_historical_fixed_dt_reuse():
    """Verify that historical clamped/fixed-dt results are explicitly prohibited from reuse."""
    contract = json.loads((HANDOFF_DIR / "contracts" / "spatial_ladder_contract.json").read_text())
    prohibition = contract.get("fixed_dt_reuse_prohibition", {})
    assert "F3_CELL3_LONG_dp0p01_a1p000_noslip_visco1_nopen" in prohibition.get("historical_case", "")
    assert "CoefDtMin=0.05" in prohibition.get("rule", "")
    assert "rejected" in prohibition.get("rule", "").lower()


def test_runner_requests_schema_and_resource_bounds():
    """Verify that CPU and GPU runner requests strictly follow ds02.runner-request.v2 and fit limits."""
    req_dir = HANDOFF_DIR / "requests"
    cpu_requests = [
        "gencase_cpu_coarse_dp015_request.json",
        "gencase_cpu_medium_dp010_request.json",
    ]
    gpu_requests = [
        "solver_gpu_coarse_dp015_request.json",
        "solver_gpu_medium_dp010_request.json",
    ]

    for fname in cpu_requests:
        req = json.loads((req_dir / fname).read_text())
        assert req["schema"] == "ds02.runner-request.v2"
        assert req["family_id"] == "F3"
        assert req["kind"] == "cpu"
        assert req["cpu_task_kind"] == "gencase"
        assert req["max_wall_seconds"] <= 300
        assert req["estimated_storage_bytes"] <= 67108864
        assert req["launch_allowed"] is False
        assert req["launch_owner"] == "root"

    for fname in gpu_requests:
        req = json.loads((req_dir / fname).read_text())
        assert req["schema"] == "ds02.runner-request.v2"
        assert req["family_id"] == "F3"
        assert req["kind"] == "qualification"
        assert req["max_wall_seconds"] <= 7200, "Solver max wall time must be <= 2h"
        assert req["estimated_storage_bytes"] <= 2147483648, "Storage must be <= 2 GiB"
        assert req["launch_allowed"] is False
        assert req["launch_owner"] == "root"
        assert req["expected_native_frames"] == 836
        assert req["complete_event_window_s"] == [0.0, 8.35]


def test_device_dispatch_placeholder_policy():
    """Verify that GPU solver requests do not hardcode foreign GPUs and use placeholder semantics."""
    req_dir = HANDOFF_DIR / "requests"
    for fname in ["solver_gpu_coarse_dp015_request.json", "solver_gpu_medium_dp010_request.json"]:
        req = json.loads((req_dir / fname).read_text())
        policy = req.get("device_dispatch_policy", {})
        assert policy.get("allowed_owned_gpus") == [2, 5, 6, 7]
        assert policy.get("protected_foreign_gpus") == [0, 1, 3, 4]
        assert policy.get("device_ids_placeholder") == "{LEASED_GPU_DEVICE_ID}"

        # Ensure foreign GPUs (0, 1, 3, 4) are not hardcoded in the command array
        for arg in req["command"]:
            assert not any(arg.startswith(f"-gpu:{fgpu}") for fgpu in [0, 1, 3, 4])


def test_observation_contracts_and_descriptive_cdf_label():
    """Verify frozen 7-metric macro contract and descriptive-only transport CDF policy."""
    contract = json.loads((HANDOFF_DIR / "contracts" / "spatial_ladder_contract.json").read_text())
    obs = contract.get("frozen_observation_contracts", {})
    metrics = obs.get("macro_metrics", [])
    expected_7_metrics = [
        "tv",
        "com_l2_over_length",
        "q90_over_length",
        "mean_velocity_over_U",
        "energy_difference",
        "common_support_velocity_over_U",
        "unmatched_support_mass",
    ]
    assert metrics == expected_7_metrics
    assert obs.get("macro_budgets", {}).get("time_output_error_budget") == 0.01
    assert obs.get("macro_budgets", {}).get("spatial_reference_budget") == 0.05
    assert obs.get("transport_cdf_status") == "descriptive_only_not_continuous_qualification"


def test_prospective_points_of_comparison_and_independent_qualification():
    """Verify prospective comparison points, independent mechanisms, and rejection of alias counting."""
    doc = json.loads((HANDOFF_DIR / "prospective_points_of_comparison.json").read_text())
    assert doc["schema"] == "ds02.root.prospective-spatial-ladder-comparison.v1"

    # Both background mechanisms present
    qual = doc.get("independent_qualification_path", {})
    assert "background_1_cell3" in qual
    assert "background_2_eccentric_baffle" in qual
    assert "study_alias_clarification" in qual
    assert "0/336" in qual["study_alias_clarification"]

    # Parameter endpoints
    for bg in ["background_1_cell3", "background_2_eccentric_baffle"]:
        eps = qual[bg]["parameter_endpoints"]
        assert eps["drive_amplitude_Gamma"] == [0.6, 0.9, 1.2]
        assert eps["fill_fraction"] == [0.18, 0.27, 0.36]
        assert eps["frequency_ratio"] == [0.8, 1.0, 1.2]


def test_audit_script_execution():
    """Verify that audit_spatial_ladder_preparation.py executes successfully and exits with code 0."""
    script_path = HANDOFF_DIR / "audit_spatial_ladder_preparation.py"
    assert script_path.exists()
    cmd = [sys.executable, str(script_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, f"Audit script failed with stderr:\n{result.stderr}\nstdout:\n{result.stdout}"
    assert "ALL 7 CHECKS PASSED" in result.stdout
