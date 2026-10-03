"""Unit tests for F2 RV4 matched CENTER coarse & medium terminal NVMe postprocess v1."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path
import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "f2_rv4eq_matched_center_terminal_nvme_postprocess_v1.py"
spec = importlib.util.spec_from_file_location("f2_matched_center_postprocess_v1", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
postprocess_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(postprocess_mod)

FAMILY_ROOT = postprocess_mod.FAMILY_ROOT
HANDOFF_ROOT = postprocess_mod.HANDOFF_ROOT
OWNER_DIR = postprocess_mod.OWNER_DIR
CONFIGS_DIR = postprocess_mod.CONFIGS_DIR
REQUESTS_DIR = postprocess_mod.REQUESTS_DIR
ARTIFACTS_DIR = postprocess_mod.ARTIFACTS_DIR
CASES = postprocess_mod.CASES
DATA_ROOT = postprocess_mod.DATA_ROOT
F2_DATA = postprocess_mod.F2_DATA


def test_verified_copy_stream_hash_and_permissions(tmp_path: Path):
    source = tmp_path / "test_source.bin"
    payload = b"center-stream-hash-test" * 1024
    source.write_bytes(payload)
    expected_sha = hashlib.sha256(payload).hexdigest()

    target = tmp_path / "private_target.bin"
    evidence = postprocess_mod.verified_copy(source, target, expected_sha, len(payload))

    assert target.is_file()
    assert target.read_bytes() == payload
    assert evidence["private_reader_sha256"] == expected_sha
    assert evidence["private_reader_bytes"] == len(payload)
    assert evidence["copy_verified_during_stream"] is True
    assert target.stat().st_mode & 0o777 == 0o400

    # Test failure on SHA mismatch
    bad_target = tmp_path / "bad_target.bin"
    with pytest.raises(postprocess_mod.ProcessError, match="SHA mismatch"):
        postprocess_mod.verified_copy(source, bad_target, "0" * 64, len(payload))


def test_cases_constant_structure():
    assert "coarse" in CASES
    assert "medium" in CASES

    coarse = CASES["coarse"]
    assert coarse["case_id"] == "F2_RV4EQ_MATCHED_CENTER_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010"
    assert coarse["dp_m"] == 0.010
    assert coarse["total_particles"] == 421566
    assert coarse["fluid_particles"] == 24576
    assert coarse["case_nmoving"] == 24150
    assert coarse["physical_hash"] == "45c579bd9fa7a4878fcd25d0e0aa6dedf6da8c4cd77cd85e0d05b928ab8b6a43"
    assert coarse["source_h5"].is_file()

    medium = CASES["medium"]
    assert medium["case_id"] == "F2_RV4EQ_MATCHED_CENTER_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010"
    assert medium["dp_m"] == 0.008
    assert medium["total_particles"] == 668673
    assert medium["fluid_particles"] == 48000
    assert medium["case_nmoving"] == 39561
    assert medium["physical_hash"] == "45c579bd9fa7a4878fcd25d0e0aa6dedf6da8c4cd77cd85e0d05b928ab8b6a43"
    assert medium["source_h5"].is_file()


def test_build_owner_metadata():
    for name, info in CASES.items():
        owner = postprocess_mod.build_owner_metadata(info)
        assert owner["family_id"] == "F2"
        assert owner["case_id"] == info["case_id"]
        assert owner["resolution"] == info["resolution"]
        assert math.isclose(owner["mass_reference"]["continuous_mass_kg"], 24.576, rel_tol=1e-9)
        assert owner["physical_binding"]["physical_condition_hash_declared"] == "45c579bd9fa7a4878fcd25d0e0aa6dedf6da8c4cd77cd85e0d05b928ab8b6a43"
        assert "cup_low_m" in owner["geometry"]
        assert "receiver_low_m" in owner["geometry"]
        assert "tray_low_m" in owner["geometry"]


def test_requests_structure():
    postprocess_mod.build_all()

    for name, info in CASES.items():
        short = info["short_name"]
        pose_req_path = REQUESTS_DIR / f"{short}_pose_nvme_request_v1.json"
        assert pose_req_path.is_file()
        pose_req = json.loads(pose_req_path.read_text(encoding="utf-8"))
        assert pose_req["schema"] == "ds02.runner-request.v2"
        assert pose_req["family_id"] == "F2"
        assert pose_req["case_id"] == info["case_id"]
        assert pose_req["kind"] == "cpu"
        assert pose_req["cpu_task_kind"] in {"labels", "audit"}
        assert pose_req["cpu_threads"] == 2
        assert pose_req["max_wall_seconds"] <= 3600
        assert pose_req["conversion_launch_forbidden"] is True
        assert pose_req["claim_boundary"]["q_n"] == "not_assessed"
        assert pose_req["independent_case_count_increment"] == 0
        for input_path in pose_req["input_files"]:
            assert Path(input_path).is_file()
            assert input_path in pose_req["input_sha256"]


def test_timing_budget_scope_separation():
    # Verify strict mathematical definition of timing budgets
    matched_allowance = postprocess_mod.MATCHED_TIMING_ALLOWANCE_S
    baseline_allowance = postprocess_mod.BASELINE_TIMING_ALLOWANCE_S
    assert math.isclose(matched_allowance, 0.0001467278159987655, rel_tol=1e-12)
    assert math.isclose(baseline_allowance, 0.0007336390799938275, rel_tol=1e-12)
    assert math.isclose(baseline_allowance / matched_allowance, 5.0, rel_tol=1e-9)

    # Observed save dt is 0.010s => half bracket is 0.0050s
    half_bracket = 0.0050
    ratio = half_bracket / matched_allowance
    assert math.isclose(ratio, 34.076698656157835, rel_tol=1e-6)
    assert ratio > 30.0  # fails its own matched prereg allowance


def test_macro_synthesis_artifact_if_present():
    synthesis_path = ARTIFACTS_DIR / "f2_rv4eq_matched_center_3dp_macro_synthesis_v1.json"
    if not synthesis_path.is_file():
        pytest.skip("Macro synthesis artifact has not been written yet")

    synthesis = json.loads(synthesis_path.read_text(encoding="utf-8"))
    assert synthesis["schema"] == "ds02.f2.matched-center-3dp-macro-synthesis.v1"
    assert synthesis["family_id"] == "F2"
    assert synthesis["background"] == "CENTER"

    # Macro 005 bindings
    macro_bind = synthesis["root_macro_description_005_binding"]
    assert Path(macro_bind["path"]).is_file()
    assert Path(macro_bind["receipt"]).is_file()
    assert macro_bind["retained_mass_diagnostics"]["coarse_vs_fine"]["original_retained_mass_5pct_diagnostic_pass"] is True
    assert macro_bind["retained_mass_diagnostics"]["medium_vs_fine"]["original_retained_mass_5pct_diagnostic_pass"] is True
    assert "unqualified" in macro_bind["com_energy_unqualified_findings"]["coarse_vs_fine"]["status"]
    assert "unqualified" in macro_bind["com_energy_unqualified_findings"]["medium_vs_fine"]["status"]

    # Invariant fluid continuum mass
    pop = synthesis["fluid_population_and_mass_continuity"]
    assert math.isclose(pop["continuum_fluid_mass_kg"], 24.576, rel_tol=1e-9)
    assert pop["cases"]["fine"]["initial_fluid_particles"] == 196608
    assert pop["cases"]["medium"]["initial_fluid_particles"] == 48000
    assert pop["cases"]["coarse"]["initial_fluid_particles"] == 24576

    # Moving boundary pose
    pose_ev = synthesis["moving_boundary_pose_fit_evidence"]
    assert pose_ev["coarse"]["moving_nodes_case_nmoving"] == 24150
    assert pose_ev["medium"]["moving_nodes_case_nmoving"] == 39561

    # Scope separation
    timing = synthesis["timing_budget_scope_separation"]
    assert math.isclose(timing["matched_prereg_allowance_s"], 0.0001467278159987655, rel_tol=1e-12)
    assert math.isclose(timing["baseline_contract_allowance_s"], 0.0007336390799938275, rel_tol=1e-12)
    assert timing["evaluation"]["coarse_and_medium_vs_matched_allowance"]["status"] == "FAIL / PENDING"

    # Qualification boundaries
    qual = synthesis["scientific_qualification_boundary"]
    assert qual["q_n_granted"] is False
    assert qual["production_granted"] is False
    assert qual["independent_physical_case_increment"] == 0
