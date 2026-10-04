"""Focused Synthetic Unit Tests for F2 True-Halfstep Preparation Suite.

Covers:
1. Authoritative source files and receipts integrity (SHA256 & byte counts)
2. Save Comparison 027 actual numerical invariants (196608 UID fates, 2151 exclusions, residence gaps)
3. Whole-XML byte-level reversibility and ElementTree undo proofs
4. Asset binding preservation (basename unchanged)
5. Root run.py tool execution compatibility
6. Prepare clone worker execution and clone-report generation
7. Native binary mass precision & rejection of legacy gate passes
8. Corrected pose 13 typed fields and sign (-1.0)
9. Strict governance flags (launch_allowed: false, no Q-N, no production)
10. Resource estimates derivation from actual completed solver receipts
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as E

import pytest

REPO_ROOT = Path(__file__).resolve().parents[6]
SUITE_DIR = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(SUITE_DIR))

from selected_transformer import (
    transform_execution_xml_bytes,
    compute_sha256,
    compute_bytes_sha256,
    audit_sources,
    F2_OFFSET_FINE_XML_PATH,
    F2_OFFSET_FINE_XML_SHA256,
    F2_OFFSET_FINE_BI4_PATH,
    F2_OFFSET_FINE_BI4_SHA256,
    F2_OFFSET_FINE_BI4_BYTES,
    F2_OFFSET_FINE_MOTION_PATH,
    F2_OFFSET_FINE_MOTION_SHA256,
    F2_OFFSET_FINE_MOTION_BYTES,
    F2_OFFSET_GENCASE_RECEIPT_PATH,
    F2_OFFSET_GENCASE_RECEIPT_SHA256,
    F2_OFFSET_SOLVER_RECEIPT_PATH,
    F2_OFFSET_SOLVER_RECEIPT_SHA256,
    F2_OFFSET_POSE_013_RECEIPT_PATH,
    F2_OFFSET_POSE_013_RECEIPT_SHA256,
    F2_OFFSET_REPORT_024_RECEIPT_PATH,
    F2_OFFSET_REPORT_024_RECEIPT_SHA256,
    F2_OFFSET_DENSE_018_RECEIPT_PATH,
    F2_OFFSET_DENSE_018_RECEIPT_SHA256,
    F2_OFFSET_POSE_022_RECEIPT_PATH,
    F2_OFFSET_POSE_022_RECEIPT_SHA256,
    F2_OFFSET_REPORT_025_RECEIPT_PATH,
    F2_OFFSET_REPORT_025_RECEIPT_SHA256,
    F2_OFFSET_SAVE_COMPARISON_027_PATH,
    F2_OFFSET_SAVE_COMPARISON_027_SHA256,
)
from prepare import prepare_truehalfstep_clone


class TestF2TrueHalfstepPreparation:
    """Test suite for F2 RV4EQ DP005 OFFSET true-halfstep preparation."""

    def test_source_files_and_receipts_exist_and_match_sha256(self):
        """All primary native sources, receipts, reports, and comparisons must exist with exact SHA256."""
        audit = audit_sources()
        assert audit["all_sources_verified"] is True
        for key, info in audit["files"].items():
            assert info["exists"] is True, f"File missing: {key}"
            assert info["actual_sha256"] == info["expected_sha256"], f"SHA256 mismatch for {key}"

    def test_save_comparison_027_invariants(self):
        """Verify Save Comparison 027 numerical invariants reported by Root."""
        assert F2_OFFSET_SAVE_COMPARISON_027_PATH.is_file()
        data = json.loads(F2_OFFSET_SAVE_COMPARISON_027_PATH.read_text(encoding="utf-8"))

        # UID fate agreement
        fates = data["destination_fates"]["aggregate_inventory"]
        assert fates["aggregate_inventory_match"] is True
        assert fates["destinations"]["unknown"]["nominal_particles"] == 2151
        assert fates["destinations"]["unknown"]["dense_particles"] == 2151
        assert fates["destinations"]["cup"]["nominal_particles"] == 0
        assert fates["destinations"]["cup"]["dense_particles"] == 0
        assert fates["destinations"]["receiver"]["nominal_particles"] == 24411
        assert fates["destinations"]["receiver"]["dense_particles"] == 24411
        assert fates["destinations"]["tray"]["nominal_particles"] == 161580
        assert fates["destinations"]["tray"]["dense_particles"] == 161580
        assert fates["destinations"]["inflight"]["nominal_particles"] == 8466
        assert fates["destinations"]["inflight"]["dense_particles"] == 8466
        assert data["destination_fates"]["per_uid_fates"]["switched_particles_count"] == 0

        # Native exclusions
        exclusions = data["native_exclusions"]
        assert exclusions["motive_1_identities_count"] == 2151
        assert exclusions["all_retained_as_unknown_invalid"] is True
        assert exclusions["physical_spill_inferred"] is False

        # Per-UID residence
        residence = data["per_uid_residence"]["by_destination"]
        inflight_mean_abs = residence["inflight"]["mass_weighted_mean_abs_gap_s"]
        inflight_max_abs = residence["inflight"]["max_abs_gap_s"]
        assert abs(inflight_mean_abs - 0.008602213998874208) < 1e-12
        assert abs(inflight_max_abs - 0.06602083257110325) < 1e-12

        # Literal closed bracket matching
        matching = data["episodic_event_matching"]
        assert matching["status"] == "strict_saved_bracket_matching_completed"
        assert matching["grand_totals"]["proven_unique_1to1_joint_count"] == 1852580
        assert matching["grand_totals"]["ambiguous_nominal_count"] == 8085
        assert matching["grand_totals"]["ambiguous_dense_count"] == 16184
        assert matching["grand_totals"]["unmatched_nominal_count"] == 0

    def test_xml_transformation_and_byte_reversibility(self):
        """XML mutation must alter ONLY execution CFL and CoefDtMin, with exact byte reversibility."""
        original_bytes = F2_OFFSET_FINE_XML_PATH.read_bytes()
        mutated_bytes, meta = transform_execution_xml_bytes(original_bytes)

        assert meta["original_sha256"] == F2_OFFSET_FINE_XML_SHA256
        assert meta["mutated_sha256"] == "b5256b5e3f6a6e64540f7d500babb77c6e25e9a499d2d34ad33bac89185410ee"
        assert meta["reversibility_verified"] is True
        assert meta["elementtree_undo_verified"] is True
        assert meta["casedef_historical_cfl_preserved"] == "0.2"
        assert meta["execution_cfl_mutated"] == "0.1"
        assert meta["execution_coefdtmin_mutated"] == "0.025"
        assert meta["dt_fixed_floor_safe"]["DtFixed"] == "0"
        assert meta["dt_fixed_floor_safe"]["DtIni"] == "0"
        assert meta["dt_fixed_floor_safe"]["DtMin"] == "0"
        assert meta["dt_fixed_floor_safe"]["unintended_fixed_dt_floor"] is False

    def test_elementtree_undo_proof(self):
        """ElementTree structural roundtrip must prove zero geometry, mass, or driver modification."""
        original_bytes = F2_OFFSET_FINE_XML_PATH.read_bytes()
        mutated_bytes, _ = transform_execution_xml_bytes(original_bytes)

        before = E.fromstring(original_bytes)
        after = E.fromstring(mutated_bytes)
        restored = E.fromstring(mutated_bytes)

        # Confirm mutation values
        cfl_val = float(after.find("./execution/constants/cflnumber").get("value"))
        params = {x.get("key"): x for x in after.findall("./execution/parameters/parameter")}
        coef_val = float(params["CoefDtMin"].get("value"))
        assert cfl_val == 0.1
        assert coef_val == 0.025
        assert float(params["DtFixed"].get("value")) == 0.0
        assert float(params["DtIni"].get("value")) == 0.0
        assert float(params["DtMin"].get("value")) == 0.0

        # Restore parameters and confirm identical tree representation
        restored.find("./execution/constants/cflnumber").set(
            "value", before.find("./execution/constants/cflnumber").get("value")
        )
        rp = {x.get("key"): x for x in restored.findall("./execution/parameters/parameter")}
        bp = {x.get("key"): x for x in before.findall("./execution/parameters/parameter")}
        rp["CoefDtMin"].set("value", bp["CoefDtMin"].get("value"))

        assert E.tostring(restored) == E.tostring(before)

    def test_root_run_py_tool_execution(self):
        """Root run.py tool must execute cleanly against binding.json and confirm passed wholeXMLundo."""
        root_run_py = Path(
            "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_f4_f6_exact_halfstep_clone_tools_037/run.py"
        )
        assert root_run_py.is_file()

        binding_file = SUITE_DIR / "binding.json"
        assert binding_file.is_file()

        with tempfile.TemporaryDirectory(prefix="test_root_run_f2_") as tmp_dir:
            out_dir = Path(tmp_dir) / "clone"
            cmd = [
                sys.executable,
                str(root_run_py),
                "--binding",
                str(binding_file),
                "--output-dir",
                str(out_dir),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            assert proc.returncode == 0, f"run.py failed: {proc.stderr}"
            assert '"exact_initial_clone": "completed"' in proc.stdout
            assert '"wholeXMLundo": "passed"' in proc.stdout
            assert (out_dir / "clone-report.json").is_file()

    def test_prepare_worker_execution(self):
        """Prepare worker must create exact cloned files with unchanged basename to preserve bindings."""
        binding_file = SUITE_DIR / "binding.json"
        binding_data = json.loads(binding_file.read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory(prefix="test_f2_prepare_") as tmp_dir:
            out_dir = Path(tmp_dir) / "prepared"
            report = prepare_truehalfstep_clone(binding_data, out_dir)

            assert report["schema"] == "ds02.f2.offset-true-halfstep-clone-report.v1"
            assert report["whole_tree_undo_proved"] is True
            assert report["q_n"] == "not_granted"
            assert report["production_approval"] == "none"

            # Check that files were written with original basename
            xml_path = Path(report["prepared_files"]["xml"]["path"])
            bi4_path = Path(report["prepared_files"]["bi4"]["path"])
            motion_path = Path(report["prepared_files"]["motion"]["path"])

            assert xml_path.name == "F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001.xml"
            assert bi4_path.name == "F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001.bi4"
            assert motion_path.name == "F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001_motion.dat"

            assert compute_sha256(xml_path) == "b5256b5e3f6a6e64540f7d500babb77c6e25e9a499d2d34ad33bac89185410ee"
            assert compute_sha256(bi4_path) == F2_OFFSET_FINE_BI4_SHA256
            assert compute_sha256(motion_path) == F2_OFFSET_FINE_MOTION_SHA256

    def test_native_mass_and_exclusion_authority(self):
        """Native binary float32 mass authority and native exclusion inventory must be strictly verified."""
        binding_file = SUITE_DIR / "binding.json"
        binding = json.loads(binding_file.read_text(encoding="utf-8"))

        single_particle_mass = binding["native_single_particle_mass_kg"]
        cohort_mass = binding["native_cohort_mass_kg"]
        fluid_particles = binding["fluid_particles"]
        exclusions_count = binding["native_exclusions_count"]
        exclusions_mass = binding["native_exclusions_mass_kg"]

        assert fluid_particles == 196608
        assert single_particle_mass == 0.0001250000059371814
        assert abs(cohort_mass - (fluid_particles * single_particle_mass)) < 1e-12
        assert abs(cohort_mass - 24.576001167297363) < 1e-12

        # Relative representation drift
        drift = abs(cohort_mass - 24.576) / 24.576
        assert abs(drift - 4.749745128457272e-08) < 1e-14
        # 1e-12 representation gate strictly fails
        assert drift > 1e-12

        # Exclusions mass
        assert exclusions_count == 2151
        assert abs(exclusions_mass - (exclusions_count * single_particle_mass)) < 1e-12
        assert abs(exclusions_mass - 0.2688750127708772) < 1e-12

    def test_corrected_pose_and_13_typed_fields(self):
        """Corrected pose and 13 typed fields standard must match root013/022 evidence."""
        eval_report_file = SUITE_DIR / "evaluation_report.json"
        eval_data = json.loads(eval_report_file.read_text(encoding="utf-8"))

        pose_std = eval_data["pose_and_13_typed_fields_standard"]
        assert pose_std["corrected_pose_control_sign"] == -1.0
        assert pose_std["moving_node_count"] == 76676
        assert pose_std["augmented_pose_dataset"] == "rigid_body_state"
        assert len(pose_std["mandatory_payload_fields"]) == 13

        field_names = [f["name"] for f in pose_std["mandatory_payload_fields"]]
        expected_fields = [
            "time", "particle_id", "particle_zone", "initial_type", "initial_mk",
            "initial_mass", "mass", "type", "mk", "valid", "position", "velocity", "density"
        ]
        assert field_names == expected_fields

    def test_runner_requests_governance(self):
        """Prepare and solver runner requests must have launch_allowed: false and strictly no claims."""
        prep_req_file = SUITE_DIR / "prepare-request.json"
        solv_req_file = SUITE_DIR / "solver-request.json"

        assert prep_req_file.is_file()
        assert solv_req_file.is_file()

        prep_data = json.loads(prep_req_file.read_text(encoding="utf-8"))
        solv_data = json.loads(solv_req_file.read_text(encoding="utf-8"))

        for req in [prep_data, solv_data]:
            assert req["launch_allowed"] is False
            assert req["launch_owner"] == "root"
            assert req["production_approval"] == "none"
            assert req["q_n_status"] == "not_assessed"
            assert req["independent_case_count_increment"] == 0

        # Dispatch guard must point to strict dispatcher
        strict_dispatcher = "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py"
        assert strict_dispatcher in solv_data["input_files"]
        assert solv_data["input_sha256"][strict_dispatcher] == "81bdd60e5de4fec362807043ab632864405f1667a0658560fb9349025aab75ec"

    def test_resource_estimates_against_actual_receipts(self):
        """Resource estimates must be strictly derived from actual baseline solver receipt without fabrication."""
        solv_receipt = json.loads(F2_OFFSET_SOLVER_RECEIPT_PATH.read_text(encoding="utf-8"))
        actual_elapsed_s = solv_receipt["elapsed_seconds"]
        actual_bytes = solv_receipt["bytes"]

        assert abs(actual_elapsed_s - 553.287853717804) < 1e-6
        assert actual_bytes == 29396068905

        # Check steps in Run.out
        run_out_path = F2_OFFSET_SOLVER_RECEIPT_PATH.parent / "solver_output" / "Run.out"
        assert run_out_path.is_file()
        run_out_text = run_out_path.read_text(encoding="utf-8")
        assert "Steps of simulation..............: 201,237" in run_out_text
        actual_steps = 201237

        eval_data = json.loads((SUITE_DIR / "evaluation_report.json").read_text(encoding="utf-8"))
        res = eval_data["resource_costs_and_budget_accounting"]["candidate_halfstep_estimates"]

        # Expected steps ~ 2x baseline
        assert res["estimated_steps"] == int(round(actual_steps * 2.0))
        # Expected GPU seconds ~ 2x baseline
        assert res["estimated_gpu_seconds"] == int(round(actual_elapsed_s * 2.0))
        assert res["required_gpu_hours"] == round((actual_elapsed_s * 2.0) / 3600.0, 3)
        assert res["required_gpu_hours"] < 0.35  # ~0.307 GPUh
