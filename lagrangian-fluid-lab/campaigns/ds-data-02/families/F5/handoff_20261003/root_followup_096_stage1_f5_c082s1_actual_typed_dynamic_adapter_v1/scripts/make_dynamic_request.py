#!/usr/bin/env python3
"""Create the disabled Root request from a fresh096 metadata binding."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab")
CAMPAIGNS = INTEGRATION / "campaigns/ds-data-02"
HANDOFF = CAMPAIGNS / "handoff_20261003"
BINDING_PATH = ROOT / "bindings/short-event-bed-audit-binding.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def required(paths: list[Path]) -> None:
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError("request inputs missing: " + ", ".join(missing))


def main() -> int:
    binding = json.loads(BINDING_PATH.read_text(encoding="utf-8"))
    worker = ROOT / "workers/bed_audit.py"
    binder = ROOT / "scripts/bind_actual_typed317_xmf318.py"
    preflight = ROOT / "scripts/preflight_fresh096.py"
    recipe = ROOT.parent / "root_followup_093_stage1_f5_c082s1_short51_pipeline_v1/canonical-physical-recipe.json"
    physical = ROOT.parent / "root_followup_093_stage1_f5_c082s1_short51_pipeline_v1/physical-binding.json"
    files = [
        INTEGRATION / ".venv/bin/python",
        INTEGRATION / "scripts/ds_data02_runtime_v2.py",
        INTEGRATION / "scripts/ds_data02_strict_dispatch_v1.py",
        HANDOFF / "root_stage1_home_floor_inventory_dispatch_142/root_home_floor_inventory_policy.py",
        HANDOFF / "root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json",
        worker, binder, preflight, BINDING_PATH,
        ROOT / "metadata/actual-typed317-xmf318-summary.json", recipe, physical,
        Path(binding["owner_metadata"]), Path(binding["gencase_receipt"]),
        Path(binding["gencase_prepared_report"]), Path(binding["initial_qa_receipt"]),
        Path(binding["initial_qa_report"]), Path(binding["short_solver_receipt"]),
        Path(binding["short_saved_state_metadata"]["path"]), Path(binding["native_conversion_receipt"]),
        Path(binding["native_conversion_report"]), Path(binding["xmf_receipt"]),
        Path(binding["xmf_manifest"]), Path(binding["canonical_generated_xml"]),
        Path(binding["xdmf"]), Path(binding["trajectory_h5"]),
    ]
    unique: list[Path] = []
    for path in files:
        path = path.resolve()
        if path not in unique:
            unique.append(path)
    required([path for path in unique if path != Path(binding["trajectory_h5"]).resolve()])
    input_sha: dict[str, str] = {}
    for path in unique:
        key = str(path)
        if path == Path(binding["trajectory_h5"]).resolve():
            # Producer-declared digest only.  This source package never opens H5.
            input_sha[key] = str(binding["trajectory_h5_sha256"])
        else:
            input_sha[key] = sha256(path)

    binding_sha = sha256(BINDING_PATH)
    request = {
        "schema": "ds02.runner-request.v2",
        "status": "disabled_until_root_review_and_registered_dynamic_audit",
        "family_id": "F5",
        "candidate_id": "C082S1_solid_fluid_recovery",
        "condition_id": "F5_RUNUP_DP020_EQUILIBRIUM_ROOT050_C_SOLID_FLUID_RECOVERY_090",
        "repair_id": "F5_BED_RECOVERY_C082S1_SOLID_FLUID_SOURCE_090",
        "case_id": binding["case_id"],
        "physical_case_id": binding["physical_case_id"],
        "attempt_id": "root-stage1-f5-c082s1-solid-fluid-recovery-short-native-bed-audit-321",
        "depends_on_attempt": "root-stage1-f5-c082s1-solid-fluid-recovery-short-native-xmf-318",
        "cpu_task_kind": "audit",
        "worker_kind": "dynamic_bed_footprint_audit",
        "launch_owner": "root",
        "cwd": str(INTEGRATION),
        "command": [
            str(INTEGRATION / ".venv/bin/python"), str(worker),
            "--binding", str(BINDING_PATH), "--trajectory-h5", binding["trajectory_h5"],
            "--xdmf", binding["xdmf"], "--output-dir", "{attempt_root}/audit-output",
        ],
        "input_files": [str(path) for path in unique],
        "input_sha256": input_sha,
        "input_sha256_provenance": {
            "metadata_and_source_files": "JSON/XML/source hashes computed for this disabled request",
            "trajectory_h5": "producer-declared output_sha256 from actual typed317 conversion-report.json; source preparation did not open or rehash H5; Root strict dispatch must revalidate on enable",
            "science_array_policy": "BI4/CSV/H5 science arrays were not opened or hashed by this source package; no BI4/CSV input is registered",
        },
        "array_edit_allowed": False,
        "arrays_allowed": False,
        "source_only": True,
        "execution_allowed": False,
        "launch": False,
        "disabled": True,
        "solver_allowed": False,
        "conversion_allowed": False,
        "diagnostic_only": True,
        "production_approval": "none",
        "q_n_granted": False,
        "full16_authorized": False,
        "full801_authorized": False,
        "independent_case_count_increment": 0,
        "estimated_peak_gpu_mib": 0,
        "estimated_storage_bytes": 2147483648,
        "cpu_threads": 2,
        "max_wall_seconds": 3600,
        "expected_dimension": 3,
        "expected_frames": 51,
        "expected_particles": 194427,
        "expected_particle_axis": 194427,
        "expected_fixed_particles": 158559,
        "expected_moving_particles": 4210,
        "expected_floating_particles": 0,
        "expected_fluid_particles": 31658,
        "dp_m": 0.02,
        "penetration_bins_m": [0.02, 0.04],
        "bed_y_bounds_m": [-0.22, 0.22],
        "native_bed_marker_mk": 50,
        "source_bed_marker_mkbound": 40,
        "actual_counts": binding["actual_counts"],
        "binding_contract": {
            "schema": binding["schema"],
            "binding_path": str(BINDING_PATH.resolve()),
            "binding_sha256": binding_sha,
            "actual_counts_full_placement_copy": binding["actual_counts"],
            "scalar_count_keys": ["total_particles", "fixed_particles", "moving_particles", "floating_particles", "fluid_particles", "solver_dimension"],
            "placement_report_sha256": binding["initial_qa_report_sha256"],
            "gencase_receipt_sha256": binding["gencase_receipt_sha256"],
            "typed_report_sha256": binding["native_conversion_report_sha256"],
            "xmf_manifest_sha256": binding["xmf_manifest_sha256"],
            "trajectory_h5_sha256_producer_declared": binding["trajectory_h5_sha256"],
            "source_h5_physical_condition_sha256": binding["source_h5_physical_condition_sha256"],
        },
        "output_contract": {
            "scan_all_51_frames": True,
            "scan_all_initial_fluid_uids_each_frame": True,
            "scope_exact_profile_x_and_bed_y": True,
            "report_one_dp_two_dp_count_fraction_depth": True,
            "report_nonfinite_and_lost_uid_unexplained": True,
            "thresholds_diagnostic_only": True,
            "native_bed_mk": 50,
            "source_mkbound": 40,
            "visual_review_required": True,
            "repair_success_not_inferred": True,
            "short_event_right_censored_0_to_1s": True,
            "full801_authorized": False,
        },
        "upstream_completed": {
            "gencase_attempt": "root-stage1-f5-c082s1-solid-fluid-recovery-genuine-gencase-293",
            "placement_attempt": "root-stage1-f5-c082s1-solid-fluid-recovery-stage1-placement-mk50-audit-315",
            "short_native_attempt": "root-stage1-f5-c082s1-solid-fluid-recovery-short-native-qualification-316",
            "typed_attempt": "root-stage1-f5-c082s1-solid-fluid-recovery-short-native-typed-nvme-317",
            "xmf_attempt": "root-stage1-f5-c082s1-solid-fluid-recovery-short-native-xmf-318",
            "all_completed_zero": True,
        },
        "physical_condition_hash_semantics": binding["physical_condition_hash_semantics"],
        "future_output_hashes": None,
        "source_arrays_read_or_hashed_by_source_agent": False,
        "root_review_required": True,
        "resource_window": {
            "launch_owner": "root",
            "gpu_hours": 512,
            "cpu_core_hours": 3840,
            "qualification_attempts": 1024,
            "production_attempts": 720,
            "home_min_free_bytes": 536870912000,
            "note": "static approval provenance only; this request is disabled and has no ledger dependency",
        },
    }
    out = ROOT / "requests/dynamic-bed-audit-request.json"
    out.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (ROOT / "metadata/request-input-sha-summary.json").write_text(json.dumps({
        "schema": "ds02.f5.c082s1.disabled-request-input-sha-summary.fresh096.v1",
        "status": "source_metadata_only",
        "attempt_id": request["attempt_id"],
        "input_sha256": input_sha,
        "trajectory_h5_sha256_source": "actual typed317 report output_sha256; not recomputed by source prep",
        "science_arrays_read_or_hashed_by_source_agent": False,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"request": str(out.resolve()), "inputs": len(unique), "binding_sha256": binding_sha, "trajectory_h5_sha256": binding["trajectory_h5_sha256"], "xdmf_sha256": binding["xdmf_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
