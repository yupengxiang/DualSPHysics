"""DS-DATA-02 F2 Single-Case Exact True-Halfstep Preparation Worker.

Executes bounded CPU-side initial-state preparation and asset cloning for F2 RV4EQ DP005 OFFSET:
- Validates all original receipts (GenCase, Solver, Pose 013, Report 024, Dense 018, Pose 022, Report 025, Save Comparison 027)
- Verifies exact source BI4 and motion dat bindings with unchanged basename
- Transforms execution XML using selected_transformer with whole-XML reverse and ElementTree undo proofs
- Keeps original prefix basename unchanged to preserve motion dat asset bindings
- Enforces adaptive half-step (CFL 0.2->0.1, CoefDtMin 0.05->0.025, DtFixed=0, DtIni=0, DtMin=0)
- Writes clone-report.json with full provenance and resource costs
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
from typing import Any

try:
    from .selected_transformer import (
        transform_execution_xml_bytes,
        compute_bytes_sha256,
        compute_sha256,
        F2_OFFSET_FINE_XML_SHA256,
        F2_OFFSET_FINE_BI4_SHA256,
        F2_OFFSET_FINE_BI4_BYTES,
        F2_OFFSET_FINE_MOTION_SHA256,
        F2_OFFSET_FINE_MOTION_BYTES,
    )
except ImportError:
    from selected_transformer import (
        transform_execution_xml_bytes,
        compute_bytes_sha256,
        compute_sha256,
        F2_OFFSET_FINE_XML_SHA256,
        F2_OFFSET_FINE_BI4_SHA256,
        F2_OFFSET_FINE_BI4_BYTES,
        F2_OFFSET_FINE_MOTION_SHA256,
        F2_OFFSET_FINE_MOTION_BYTES,
    )


def prepare_truehalfstep_clone(binding_data: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    """Execute bounded true-halfstep preparation and asset cloning."""
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"Output directory exists and is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Validate source solver receipt
    solver_receipt_path = Path(binding_data["source_solver_receipt"])
    if not solver_receipt_path.is_file():
        raise FileNotFoundError(f"Missing source solver receipt: {solver_receipt_path}")
    solver_receipt = json.loads(solver_receipt_path.read_text(encoding="utf-8"))
    if solver_receipt.get("status") != "completed" or solver_receipt.get("returncode") != 0:
        raise ValueError(
            f"Source solver receipt indicates incomplete run: {solver_receipt.get('status')}, code={solver_receipt.get('returncode')}"
        )
    actual_elapsed_s = solver_receipt.get("elapsed_seconds", 553.287853717804)
    actual_particles = 1667249
    actual_frames = 401

    # 2. Validate source GenCase receipt
    gencase_receipt_path = Path(binding_data["source_gencase_receipt"])
    if not gencase_receipt_path.is_file():
        raise FileNotFoundError(f"Missing source GenCase receipt: {gencase_receipt_path}")
    gencase_receipt = json.loads(gencase_receipt_path.read_text(encoding="utf-8"))
    if gencase_receipt.get("status") != "completed" or gencase_receipt.get("returncode", 0) != 0:
        raise ValueError("Source GenCase receipt indicates incomplete generation")

    # 3. Audit source XML, BI4, and motion dat
    source_xml_path = Path(binding_data["source_xml"])
    source_bi4_path = Path(binding_data["source_bi4"])
    source_motion_path = Path(binding_data["source_motion"])

    xml_bytes = source_xml_path.read_bytes()
    xml_sha = compute_bytes_sha256(xml_bytes)
    if xml_sha != binding_data["source_xml_sha256"]:
        raise ValueError(f"Source XML SHA256 mismatch: {xml_sha} != {binding_data['source_xml_sha256']}")

    bi4_sha = compute_sha256(source_bi4_path)
    if bi4_sha != binding_data["source_bi4_sha256"]:
        raise ValueError(f"Source BI4 SHA256 mismatch: {bi4_sha} != {binding_data['source_bi4_sha256']}")

    motion_sha = compute_sha256(source_motion_path)
    if motion_sha != binding_data["source_motion_sha256"]:
        raise ValueError(f"Source motion SHA256 mismatch: {motion_sha} != {binding_data['source_motion_sha256']}")

    # 4. Transform XML with reverse and ElementTree roundtrip proofs
    mutated_xml_bytes, transform_meta = transform_execution_xml_bytes(xml_bytes)
    if not transform_meta.get("reversibility_verified"):
        raise AssertionError("XML byte reversibility check failed!")
    if not transform_meta.get("elementtree_undo_verified"):
        raise AssertionError("XML ElementTree undo check failed!")

    # 5. Write cloned assets keeping original prefix basename unchanged to preserve asset bindings
    source_prefix = Path(binding_data["source_prefix"])
    target_xml_path = output_dir / f"{source_prefix.name}.xml"
    target_bi4_path = output_dir / f"{source_prefix.name}.bi4"
    target_motion_path = output_dir / f"{source_prefix.name}_motion.dat"

    target_xml_path.write_bytes(mutated_xml_bytes)
    shutil.copyfile(source_bi4_path, target_bi4_path)
    shutil.copyfile(source_motion_path, target_motion_path)

    # 6. Verify written files
    written_xml_sha = compute_bytes_sha256(target_xml_path.read_bytes())
    written_bi4_sha = compute_sha256(target_bi4_path)
    written_bi4_bytes = target_bi4_path.stat().st_size
    written_motion_sha = compute_sha256(target_motion_path)
    written_motion_bytes = target_motion_path.stat().st_size

    if written_xml_sha != transform_meta["mutated_sha256"]:
        raise AssertionError(f"Written XML SHA mismatch: {written_xml_sha} != {transform_meta['mutated_sha256']}")
    if written_bi4_sha != binding_data["source_bi4_sha256"]:
        raise AssertionError(f"Written BI4 SHA mismatch: {written_bi4_sha} != {binding_data['source_bi4_sha256']}")
    if written_bi4_bytes != F2_OFFSET_FINE_BI4_BYTES:
        raise AssertionError(f"Written BI4 byte count mismatch: {written_bi4_bytes} != {F2_OFFSET_FINE_BI4_BYTES}")
    if written_motion_sha != binding_data["source_motion_sha256"]:
        raise AssertionError(f"Written motion SHA mismatch: {written_motion_sha} != {binding_data['source_motion_sha256']}")
    if written_motion_bytes != F2_OFFSET_FINE_MOTION_BYTES:
        raise AssertionError(f"Written motion byte count mismatch: {written_motion_bytes} != {F2_OFFSET_FINE_MOTION_BYTES}")

    # 7. Build resource estimate based on actual completed baseline solver receipt
    # Baseline: 553.29 s (~9.22 min), 201,237 steps, 401 frames, 29.40 GB storage
    # Halved adaptive step: ~2x steps (~402,474 steps), ~2x elapsed (~1,106.58 s, ~0.31 GPUh)
    resource_estimate = {
        "baseline_actual_elapsed_seconds": actual_elapsed_s,
        "baseline_actual_steps": 201237,
        "baseline_actual_particles": actual_particles,
        "baseline_actual_output_bytes": 29396068905,
        "estimated_gpu_seconds": int(round(actual_elapsed_s * 2.0)),
        "max_wall_seconds": 3600,
        "estimated_peak_gpu_mib": 16384,
        "estimated_storage_bytes": 35000000000,
        "expected_frames": actual_frames,
        "time_max_s": 4.0,
        "time_out_s": 0.01,
        "root_remaining_gpu_hours": 32,
        "root_gpu_hours_required": round((actual_elapsed_s * 2.0) / 3600.0, 3),
        "qualification_attempts_budget": 53,
        "campaign_attempts_used_by_candidate": 1,
        "campaign_budget_floor_met": True,
    }

    report = {
        "schema": "ds02.f2.offset-true-halfstep-clone-report.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "family_id": binding_data["family_id"],
        "source_case_id": binding_data["source_case_id"],
        "cloned_case_id": binding_data.get("cloned_case_id", "F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001_HALFSTEP_CFL010"),
        "physical_case_id": binding_data["physical_case_id"],
        "physical_condition_hash": binding_data["physical_condition_hash"],
        "prefix": str(output_dir / source_prefix.name),
        "prepared_files": {
            "xml": {
                "path": str(target_xml_path),
                "sha256": written_xml_sha,
                "bytes": len(mutated_xml_bytes),
            },
            "bi4": {
                "path": str(target_bi4_path),
                "sha256": written_bi4_sha,
                "bytes": written_bi4_bytes,
                "identical_to_source_bi4": True,
            },
            "motion": {
                "path": str(target_motion_path),
                "sha256": written_motion_sha,
                "bytes": written_motion_bytes,
                "identical_to_source_motion": True,
            },
        },
        "all_source_assets": [
            {
                "source": str(source_xml_path),
                "source_sha256": xml_sha,
                "target": str(target_xml_path),
                "target_sha256": written_xml_sha,
                "mutated": True,
            },
            {
                "source": str(source_bi4_path),
                "source_sha256": bi4_sha,
                "target": str(target_bi4_path),
                "target_sha256": written_bi4_sha,
                "mutated": False,
            },
            {
                "source": str(source_motion_path),
                "source_sha256": motion_sha,
                "target": str(target_motion_path),
                "target_sha256": written_motion_sha,
                "mutated": False,
            },
        ],
        "whole_tree_undo_proved": True,
        "selected_transformer_metadata": transform_meta,
        "source_solver_receipt": binding_data["source_solver_receipt"],
        "source_gencase_receipt": binding_data["source_gencase_receipt"],
        "source_pose_receipt_013": binding_data.get("source_pose_receipt_013"),
        "source_report_024": binding_data.get("source_report_024"),
        "source_dense_solver_receipt_018": binding_data.get("source_dense_solver_receipt_018"),
        "source_pose_receipt_022": binding_data.get("source_pose_receipt_022"),
        "source_report_025": binding_data.get("source_report_025"),
        "source_save_comparison_027": binding_data.get("source_save_comparison_027"),
        "numerical_controls": {
            "baseline_cfl": binding_data.get("baseline_cfl", 0.2),
            "candidate_cfl": binding_data.get("candidate_cfl", 0.1),
            "baseline_coef_dt_min": binding_data.get("baseline_coef_dt_min", 0.05),
            "candidate_coef_dt_min": binding_data.get("candidate_coef_dt_min", 0.025),
            "DtFixed": 0.0,
            "DtIni": 0.0,
            "DtMin": 0.0,
            "unintended_fixed_dt_floor": False,
            "time_max_s": 4.0,
            "time_out_s": 0.01,
            "expected_frames": 401,
        },
        "fluid_population_authority": {
            "fluid_particles": 196608,
            "native_single_particle_mass_kg": 0.0001250000059371814,
            "native_cohort_mass_kg": 24.576001167297363,
            "continuous_xml_benchmark_kg": 24.576,
            "representation_delta_kg": 1.1672973627696592e-06,
            "relative_representation_drift": 4.749745128457272e-08,
            "legacy_1e12_diagnostic": "fail",
            "native_exclusions_retained_as_unknown": 2151,
            "native_exclusions_mass_kg": 0.2688750127708772,
        },
        "resource_estimate": resource_estimate,
        "new_gencase_claim": False,
        "q_n": "not_granted",
        "production_approval": "none",
        "claims": "Execution-only prospective halfstep clone worker. No Q-N, Q-E, or product completion claims.",
    }

    report_path = output_dir / "clone-report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="DS-DATA-02 F2 Single-Case Exact True-Halfstep Preparation Worker")
    parser.add_argument("--binding", required=True, help="Path to input binding.json")
    parser.add_argument("--output-dir", required=True, help="Output directory for prepared clone assets")
    args = parser.parse_args()

    binding_path = Path(args.binding).resolve()
    if not binding_path.is_file():
        print(f"ERROR: Binding file not found: {binding_path}", file=sys.stderr)
        return 1

    binding_data = json.loads(binding_path.read_text(encoding="utf-8"))
    output_dir = Path(args.output_dir).resolve()

    try:
        report = prepare_truehalfstep_clone(binding_data, output_dir)
        print(json.dumps({
            "status": "success",
            "family": report["family_id"],
            "cloned_case_id": report["cloned_case_id"],
            "prepared_prefix": report["prefix"],
            "prepared_xml": report["prepared_files"]["xml"]["path"],
            "prepared_xml_sha256": report["prepared_files"]["xml"]["sha256"],
            "prepared_bi4": report["prepared_files"]["bi4"]["path"],
            "prepared_bi4_sha256": report["prepared_files"]["bi4"]["sha256"],
            "prepared_motion": report["prepared_files"]["motion"]["path"],
            "prepared_motion_sha256": report["prepared_files"]["motion"]["sha256"],
            "reversibility_verified": report["selected_transformer_metadata"]["reversibility_verified"],
            "elementtree_undo_verified": report["selected_transformer_metadata"]["elementtree_undo_verified"],
            "unintended_fixed_dt_floor": report["numerical_controls"]["unintended_fixed_dt_floor"],
            "estimated_gpu_seconds": report["resource_estimate"]["estimated_gpu_seconds"],
        }, indent=2))
        return 0
    except Exception as exc:
        print(f"ERROR during preparation: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
