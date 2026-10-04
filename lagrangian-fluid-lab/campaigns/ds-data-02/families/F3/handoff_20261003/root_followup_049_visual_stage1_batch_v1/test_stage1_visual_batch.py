#!/usr/bin/env python3
"""Comprehensive Unit Tests for Stage 1 Visual Inspection & Batch 1 (Followup 049).

Campaign: DS-DATA-02
Family: F3 (Two-Axis Tank Sloshing)
Authority: Root Followup 049 under F3 isolated worktree ds-data-02-f6
"""

import io
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from twoaxis_pitch_forcing_transformer import (
    DEFAULT_FREQ_Y,
    DEFAULT_KY,
    DEFAULT_OMEGA_Y,
    DEFAULT_PERIOD_Y,
    DEFAULT_PHASE_Y,
    DEFAULT_RAMP_DURATION,
    EXPECTED_END_TIME,
    EXPECTED_END_TOKEN,
    EXPECTED_NOMINAL_ROWS,
    EXPECTED_START_TIME,
    EXPECTED_START_TOKEN,
    GRAVITY_Z,
    PINNED_NOMINAL_FORCING_SHA256,
    compute_sha256,
    evaluate_envelope,
    evaluate_transverse_acc,
    format_coord,
    transform_twoaxis_row,
    transform_twoaxis_forcing_stream,
)
from gencase_patch_generator import semantic_xml

SCOPE_DIR = Path(__file__).resolve().parent
DEFINITIONS_DIR = SCOPE_DIR / "definitions"
BINDINGS_DIR = SCOPE_DIR / "bindings"
REQUESTS_DIR = SCOPE_DIR / "requests"
PARAM_TABLE_PATH = SCOPE_DIR / "batch_param_table.json"


class TestTransformerPhysics:
    """Validate mathematical formulation of 2-axis forcing transformer."""

    def test_fundamental_transverse_eigenfrequency(self):
        w = 0.18
        h = 0.09
        g = 9.81
        ky = math.pi / w
        assert pytest.approx(ky, rel=1e-6) == DEFAULT_KY
        omega = math.sqrt(g * ky * math.tanh(ky * h))
        assert pytest.approx(omega, rel=1e-6) == DEFAULT_OMEGA_Y
        assert pytest.approx(omega / (2.0 * math.pi), rel=1e-6) == DEFAULT_FREQ_Y
        assert pytest.approx(1.0 / DEFAULT_FREQ_Y, rel=1e-6) == DEFAULT_PERIOD_Y
        assert 12.53 < DEFAULT_OMEGA_Y < 12.54

    def test_smooth_hann_envelope_boundary_conditions(self):
        # Startup boundary
        assert evaluate_envelope(0.0) == 0.0
        # Quarter ramp
        assert 0.0 < evaluate_envelope(0.125) < 0.5
        # Half ramp
        assert pytest.approx(evaluate_envelope(0.25), abs=1e-9) == 0.5
        # Full ramp reached
        assert pytest.approx(evaluate_envelope(0.50), abs=1e-9) == 1.0
        # Interior steady plateau
        assert evaluate_envelope(1.0) == 1.0
        assert evaluate_envelope(4.175) == 1.0
        assert evaluate_envelope(7.85) == 1.0
        # Shutdown half ramp
        assert pytest.approx(evaluate_envelope(7.85 + 0.25), abs=1e-9) == 0.5
        # Shutdown end
        assert pytest.approx(evaluate_envelope(8.35), abs=1e-9) == 0.0
        # Outside window
        assert evaluate_envelope(-0.01) == 0.0
        assert evaluate_envelope(8.36) == 0.0

    def test_transverse_acceleration_envelope_and_bounds(self):
        ay_amp = 0.50
        # At t=0, a_y(0) must be identically 0.0
        assert evaluate_transverse_acc(0.0, amplitude_y=ay_amp) == 0.0
        # At t=8.35, a_y(8.35) must be identically 0.0
        assert pytest.approx(evaluate_transverse_acc(8.35, amplitude_y=ay_amp), abs=1e-9) == 0.0
        # For arbitrary time, magnitude bounded by amplitude
        for t in np.linspace(0.0, 8.35, 100):
            val = evaluate_transverse_acc(float(t), amplitude_y=ay_amp)
            assert abs(val) <= ay_amp + 1e-12

    def test_zero_drive_identity(self):
        # Nominal sample row: t;ax;ay;az;alphax;alphay;alphaz
        sample = ["0.500000", "0.123456", "0.0", "-9.750000", "0.0", "0.312057", "0.0"]
        trans = transform_twoaxis_row(
            sample,
            amplitude_x=1.0,
            amplitude_y=0.0,
            omega_y=DEFAULT_OMEGA_Y,
            phase_y=0.0,
            tau_ramp=DEFAULT_RAMP_DURATION,
        )
        assert trans == sample

    def test_pitch_amplitude_scaling_zero_drive_formula(self):
        # Test zero-drive longitudinal formula
        ax_nom = 0.40
        az_nom = -9.61  # az_nom - gz = 0.20
        alphay_nom = 0.50
        sample = ["1.000000", str(ax_nom), "0.0", str(az_nom), "0.0", str(alphay_nom), "0.0"]

        # Scale by 0.90
        trans_0p90 = transform_twoaxis_row(sample, amplitude_x=0.90, amplitude_y=0.0)
        assert pytest.approx(float(trans_0p90[1]), rel=1e-7) == 0.90 * ax_nom
        expected_az_0p90 = GRAVITY_Z + 0.90 * (az_nom - GRAVITY_Z)
        assert pytest.approx(float(trans_0p90[3]), rel=1e-7) == expected_az_0p90
        assert pytest.approx(float(trans_0p90[5]), rel=1e-7) == 0.90 * alphay_nom

        # Scale by 1.10
        trans_1p10 = transform_twoaxis_row(sample, amplitude_x=1.10, amplitude_y=0.0)
        assert pytest.approx(float(trans_1p10[1]), rel=1e-7) == 1.10 * ax_nom
        expected_az_1p10 = GRAVITY_Z + 1.10 * (az_nom - GRAVITY_Z)
        assert pytest.approx(float(trans_1p10[3]), rel=1e-7) == expected_az_1p10
        assert pytest.approx(float(trans_1p10[5]), rel=1e-7) == 1.10 * alphay_nom

    def test_format_coord_double_roundtrip(self):
        val = 12.345678901234567
        s = format_coord(val)
        assert float(s) == val
        with pytest.raises(ValueError):
            format_coord(float("nan"))
        with pytest.raises(ValueError):
            format_coord(float("inf"))

    def test_stream_processor_guards(self):
        # Header + 2 data rows with invalid start token
        bad_stream = io.StringIO("# Header\n0.01;0;0;-9.81;0;0;0\n8.35;0;0;-9.81;0;0;0\n")
        out = io.StringIO()
        with pytest.raises(ValueError, match="Strict start time violation"):
            transform_twoaxis_forcing_stream(bad_stream, out, expected_rows=2, expected_start_time=0.0)


class TestBatchParameterTable:
    """Validate 8 independent physical cases batch specification."""

    def test_param_table_schema_and_case_count(self):
        assert PARAM_TABLE_PATH.exists()
        table = json.loads(PARAM_TABLE_PATH.read_text())
        assert table["schema"] == "ds02.f3.stage1-batch8-param-table.v1"
        assert table["batch_target_independent_cases"] == 8
        cases = table["cases"]
        assert len(cases) == 8

    def test_anchor_case_identity_and_status(self):
        table = json.loads(PARAM_TABLE_PATH.read_text())
        anchor = table["cases"][0]
        assert anchor["case_id"] == "F3_TWOAXIS_AY0P50_P1P00_NOMINAL"
        assert anchor["role"] == "anchor_user_accepted"
        assert anchor["transverse_amplitude_m_s2"] == 0.50
        assert anchor["pitch_amplitude_ratio"] == 1.00
        assert anchor["physical_condition_sha256"] == "49e319c0a874733707a028e916362e74e2301d6681e34bc6b717581dbd7edaeb"
        assert anchor["actual_forcing_sha256"] == "a4afb8a99ba1e7404b2892b84a2d2b293b11653d792a118867abfaec6593fb48"
        assert anchor["numerical_precision_status"] == "not accepted"

    def test_physical_uniqueness_of_all_8_cases(self):
        table = json.loads(PARAM_TABLE_PATH.read_text())
        coords = set()
        for c in table["cases"]:
            coord = (c["transverse_amplitude_m_s2"], c["pitch_amplitude_ratio"])
            assert coord not in coords, f"Duplicate physical parameter coordinate: {coord}"
            coords.add(coord)
        assert len(coords) == 8

    def test_minimal_endpoints_and_interior_coverage(self):
        table = json.loads(PARAM_TABLE_PATH.read_text())
        ay_vals = {c["transverse_amplitude_m_s2"] for c in table["cases"]}
        ap_vals = {c["pitch_amplitude_ratio"] for c in table["cases"]}
        # Ay coverage: endpoints 0.25, 0.75; interior 0.375, 0.50, 0.625
        assert ay_vals == {0.25, 0.375, 0.50, 0.625, 0.75}
        # Pitch coverage: endpoints 0.90, 1.10; nominal 1.00
        assert ap_vals == {0.90, 1.00, 1.10}

    def test_non_recount_policy_enforcement(self):
        table = json.loads(PARAM_TABLE_PATH.read_text())
        rules = table["counting_rules"]
        assert "NEVER count as separate physical cases" in rules["resolution_ladder_policy"]
        assert "do NOT increment" in rules["reruns_and_time_slices"]


class TestDefinitionsAndBindings:
    """Validate XML definitions and binding files."""

    def test_all_definitions_exist_and_match_anchor_hash(self):
        anchor_hash = "d8a2ffdccd0687f8a26792c6f412a7c5b95a982874ef7471f7ff23e59f24bf74"
        plain_xml = DEFINITIONS_DIR / "F3_CELL3_plain_0p006_Def.xml"
        assert plain_xml.exists()
        assert compute_sha256(plain_xml) == anchor_hash

        for xml_path in DEFINITIONS_DIR.glob("*.xml"):
            assert compute_sha256(xml_path) == anchor_hash, f"Hash mismatch in {xml_path.name}"

    def test_definition_xml_casedef_semantic_structure(self):
        plain_xml = DEFINITIONS_DIR / "F3_CELL3_plain_0p006_Def.xml"
        root = ET.parse(plain_xml).getroot()
        casedef = root.find("casedef")
        assert casedef is not None
        constants = root.find("./casedef/constantsdef")
        assert constants is not None
        assert constants.find("gravity").get("z") == "-9.81"
        assert constants.find("cflnumber").get("value") == ".05"
        geometry = root.find("./casedef/geometry/definition")
        assert geometry.get("dp") == "0.006"

    def test_all_8_binding_files_exist_and_consistent(self):
        table = json.loads(PARAM_TABLE_PATH.read_text())
        for c in table["cases"]:
            c_idx = c["index"]
            cid = c["case_id"].lower()
            binding_path = BINDINGS_DIR / f"binding_{c_idx:02d}_{cid}.json"
            assert binding_path.exists(), f"Binding missing: {binding_path.name}"
            binding = json.loads(binding_path.read_text())
            assert binding["case_id"] == c["case_id"]
            assert binding["transverse_amplitude_m_s2"] == c["transverse_amplitude_m_s2"]
            assert binding["pitch_amplitude_ratio"] == c["pitch_amplitude_ratio"]
            assert binding["expected_frames"] == 836
            assert binding["time_window_s"] == [0.0, 8.35]
            assert binding["numerical_precision_status"] == "not accepted"
            if c["role"] == "anchor_user_accepted":
                assert binding["visual_review_status"] == "pending root review"
            else:
                assert binding["visual_review_status"] == "disabled until Root visual review anchor"


class TestParaViewRendererSource:
    """Validate stand-alone ParaView animation renderer source constraints."""

    def test_renderer_script_exists_and_syntax_clean(self):
        script_path = SCOPE_DIR / "paraview_animation_renderer.py"
        assert script_path.exists()
        code = script_path.read_text()
        compile(code, str(script_path), "exec")

    def test_strictly_no_h5py_in_pvpython_script(self):
        script_path = SCOPE_DIR / "paraview_animation_renderer.py"
        code = script_path.read_text()
        # Ensure 'h5py' is not imported
        assert "import h5py" not in code
        assert "from h5py" not in code

    def test_xdmfreader_exact_type_assertion_present(self):
        script_path = SCOPE_DIR / "paraview_animation_renderer.py"
        code = script_path.read_text()
        assert "XDMFReader(" in code
        assert "reader.GetXMLName() == 'XdmfReader'" in code or 'reader.GetXMLName() == "XdmfReader"' in code

    def test_fixed_boxwalls_opacity_approx_0p15(self):
        script_path = SCOPE_DIR / "paraview_animation_renderer.py"
        code = script_path.read_text()
        assert "boundary_opacity: float = 0.15" in code or "Opacity = boundary_opacity" in code

    def test_dual_view_and_scientific_projection(self):
        script_path = SCOPE_DIR / "paraview_animation_renderer.py"
        code = script_path.read_text()
        assert "CreateLayout" in code
        assert "SplitHorizontal" in code
        assert "CameraParallelProjection = 1" in code
        assert "1.10, -1.60, 0.95" in code or "1.1, -1.6, 0.95" in code  # Isometric
        assert "0.0, -2.00, 0.22" in code or "0, -2, 0.22" in code  # Transverse side

    def test_full_836_frames_and_diagnostics(self):
        script_path = SCOPE_DIR / "paraview_animation_renderer.py"
        code = script_path.read_text()
        assert "np.isfinite(points[valid_arr]).all()" in code
        assert "np.testing.assert_array_equal(ids_arr, first_ids" in code
        assert "np.testing.assert_array_equal(zones_arr, first_zones" in code
        assert "contact_sheet" in code or "sheet_frames" in code
        assert "full_saved_animation.gif" in code
        assert "case.pvsm" in code
        assert "PRECISION NOT ACCEPTED" in code


class TestRunnerRequestsSafety:
    """Validate strict unlaunchable status and governance on all runner requests."""

    def test_all_requests_launch_allowed_is_false(self):
        request_files = list(REQUESTS_DIR.glob("*.json"))
        assert len(request_files) == 9  # 1 ParaView render + 8 GenCase preparation
        for req_path in request_files:
            req = json.loads(req_path.read_text())
            assert req["launch_allowed"] is False, f"launch_allowed is True in {req_path.name}!"
            assert req["launch_owner"] == "root"
            assert req["q_n"] == "not_granted"
            assert req["production_approval"].startswith("none")
            assert req["cpu_threads"] <= 2
            assert req["schema"] == "ds02.runner-request.v2"
