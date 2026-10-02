#!/usr/bin/env python3
"""Prepare deferred RV4EQ full-state pose/lifecycle/label requests.

The solver receipts and native PartVTKOut report are real inputs.  The H5,
conversion report, and converter receipt are intentionally *deferred* because
the root-owned conversion jobs have not both reached terminal state.  This
producer writes owner metadata and non-runnable label requests whose missing
terminal bindings must be filled with actual hashes before shared-runner
dispatch.  It never launches conversion or labels and never grants Q-I/Q-N.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


FAMILY_ROOT = Path(__file__).resolve().parent
WORKTREE_ROOT = FAMILY_ROOT.parents[4]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
F2_DATA_ROOT = DATA_ROOT / "families/F2"
INTEGRATION_LAB = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab")
NATIVE_REPORT = F2_DATA_ROOT / "F2_RV4EQ_NATIVE_PARTVTKOUT_DIAGNOSTIC_20261003_V2/rv4-native-partvtkout-baseline-002/rv4-native-partvtkout-diagnostic.json"
CORRECTED_NATIVE_REPORT = F2_DATA_ROOT / "F2_RV4EQ_NATIVE_PARTVTKOUT_DIAGNOSTIC_20261003_V2/rv4-native-partvtkout-baseline-002/rv4-native-typed-identity-correction.json"
CORRECTION_SCRIPT = FAMILY_ROOT / "f2_rv4eq_native_typed_identity_correction_v1.py"
V3_ROOT = FAMILY_ROOT / "rv4_equivalent_dp005/postprocess_handoff_v3_terminal_bound"
V3_MANIFEST = V3_ROOT / "postprocess_handoff_manifest_v3_terminal_bound.json"
LABELS = FAMILY_ROOT / "f2_handoff_20261002_v6_labels.py"
EVENT_OPERATOR = FAMILY_ROOT / "f2_handoff_20261002_event_semantics_v6.py"
EVENT_MANIFEST = FAMILY_ROOT / "handoff_20261002/event_semantics_v6/operator_manifest.json"
POSE_HELPER = INTEGRATION_LAB / "scripts/ds_data02_convert.py"
RUNTIME = INTEGRATION_LAB / "scripts/ds_data02_runtime_v2.py"
STRICT = INTEGRATION_LAB / "scripts/ds_data02_strict_dispatch_v1.py"
CONVERTER = INTEGRATION_LAB / "scripts/ds_data02_direct_convert.py"
PYTHON = WORKTREE_ROOT / "lagrangian-fluid-lab/.venv/bin/python"
OUTPUT_ROOT = FAMILY_ROOT / "handoff_20261003/rv4_fullstate_postprocess_v1"
SCHEMA = "ds-data-02.f2.rv4eq-fullstate-postprocess-handoff.v1"
CONTINUOUS_MASS_KG = 24.576
EXPECTED_FRAMES = 401

CASES = {
    "CENTER": {
        "case_id": "F2_RV4EQ_DP005_CENTER_V1_BASELINE_SAVE001",
        "physical_case_id": "F2_RV4EQ_DP005_CENTER_V1",
        "owner": V3_ROOT / "owner_metadata/F2_RV4EQ_DP005_CENTER_V1_BASELINE_SAVE001.owner.v3.json",
        "conversion_request": V3_ROOT / "conversion_requests/F2_RV4EQ_DP005_CENTER_V1_BASELINE_SAVE001_conversion_request_v3_terminal_bound.json",
        "conversion_attempt_id": "conversion-f2_rv4eq_dp005_center_v1_baseline_save001-fullstate-root-reviewed-004",
        "mechanism_id": "center_catch",
    },
    "OFFSET": {
        "case_id": "F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001",
        "physical_case_id": "F2_RV4EQ_DP005_OFFSET_V1",
        "owner": V3_ROOT / "owner_metadata/F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001.owner.v3.json",
        "conversion_request": V3_ROOT / "conversion_requests/F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001_conversion_request_v3_terminal_bound.json",
        "conversion_attempt_id": "conversion-f2_rv4eq_dp005_offset_v1_baseline_save001-fullstate-v3-terminal-bound-001",
        "mechanism_id": "offset_spill",
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} missing: {path}")
    return path


def load(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(require(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object: {path}")
    return value


def binding(path: Path, label: str) -> dict[str, Any]:
    path = require(path, label)
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size}


def deferred_binding(path: Path, *, role: str, required_status: str = "completed") -> dict[str, Any]:
    """Describe a future output without inventing a digest or terminal status."""
    return {
        "path": str(path),
        "sha256": None,
        "bytes": None,
        "role": role,
        "required_status": required_status,
        "status": "awaiting_terminal_converter_receipt",
        "must_bind_actual_hash_before_dispatch": True,
    }


def solver_paths(case_id: str) -> dict[str, Path]:
    case_root = F2_DATA_ROOT / case_id
    runparts = next(case_root.glob("*/solver_output/RunPARTs.csv"))
    output = runparts.parent
    attempt = output.parent
    data = output / "data"
    return {
        "attempt": attempt,
        "receipt": attempt / "execution-receipt.json",
        "run_out": output / "Run.out",
        "run_csv": output / "Run.csv",
        "runparts": runparts,
        "partinfo": data / "PartInfo.ibi4",
        "part_first": data / "Part_0000.bi4",
        "part_middle": data / "Part_0200.bi4",
        "part_last": data / "Part_0400.bi4",
    }


def generated_inputs(case_id: str) -> dict[str, Path]:
    prefix = F2_DATA_ROOT / "F2_RV4EQ_DP005_NATIVE_INPUTS_20261002" / case_id
    return {"xml": prefix / f"{case_id}.xml", "motion": prefix / f"{case_id}_motion.dat"}


def native_case(report: dict[str, Any], background: str) -> dict[str, Any]:
    for case in report.get("cases", []):
        if str(case.get("background")) == background:
            return case
    raise ValueError(f"native report has no {background} case")


def static_inputs(case: dict[str, Any], paths: dict[str, Path], generated: dict[str, Path], owner: Path, conversion_request: Path, native_case_value: dict[str, Any]) -> list[Path]:
    conversion = load(conversion_request, "terminal-bound conversion request")
    gencase_receipt = require(Path(str(conversion["gencase_receipt"])), "GenCase receipt")
    return [
        FAMILY_ROOT / Path(__file__).name,
        LABELS,
        EVENT_OPERATOR,
        EVENT_MANIFEST,
        POSE_HELPER,
        CONVERTER,
        RUNTIME,
        STRICT,
        FAMILY_ROOT / "quality_contract.json",
        FAMILY_ROOT / "event_definitions.json",
        FAMILY_ROOT / "integration_save_plan.json",
        FAMILY_ROOT / "case_registry.jsonl",
        FAMILY_ROOT / "definitions/reference_matrix.json",
        FAMILY_ROOT.parents[1] / "GOAL_ZH.md",
        owner,
        conversion_request,
        gencase_receipt,
        NATIVE_REPORT,
        CORRECTED_NATIVE_REPORT,
        CORRECTION_SCRIPT,
        paths["receipt"], paths["run_out"], paths["run_csv"], paths["runparts"],
        paths["partinfo"], paths["part_first"], paths["part_middle"], paths["part_last"],
        generated["xml"], generated["motion"],
    ]


def owner_metadata(background: str, case: dict[str, Any], paths: dict[str, Path], generated: dict[str, Path], v3_owner: Path, conversion_request: Path, native: dict[str, Any], conversion_attempt: Path) -> dict[str, Any]:
    old = load(v3_owner, f"{background} v3 owner metadata")
    conversion = load(conversion_request, f"{background} terminal-bound conversion request")
    gencase_receipt = require(Path(str(conversion["gencase_receipt"])), f"{background} GenCase receipt")
    raw_native_report_binding = binding(NATIVE_REPORT, "immutable raw native PartVTKOut report")
    native_report_binding = binding(CORRECTED_NATIVE_REPORT, "corrected typed native PartVTKOut report")
    native_records = native["partvtkout_exclusions"]["enriched_records"]
    owner = {
        "schema": "ds-data-02.f2.rv4eq-fullstate-owner.v1-deferred",
        "family_id": "F2",
        "background": background,
        "case_id": case["case_id"],
        "physical_case_id": case["physical_case_id"],
        "mechanism_id": case["mechanism_id"],
        "scope_id": old.get("scope_id"),
        "physical_condition_hash": old.get("physical_condition_hash_declared"),
        "physical_binding_sha256": old.get("physical_binding_sha256"),
        "numerical_recipe_hash": old.get("numerical_recipe_hash_declared"),
        "continuous_initial_mass_kg": CONTINUOUS_MASS_KG,
        "lineage": {
            "previous_owner": binding(v3_owner, "v3 owner metadata"),
            "conversion_request": binding(conversion_request, "terminal-bound conversion request"),
            "gencase_receipt": binding(gencase_receipt, "GenCase receipt"),
            "solver_receipt": binding(paths["receipt"], "completed solver receipt"),
            "terminal_semantics": old.get("terminal_semantics_report"),
            "native_partvtkout_report": native_report_binding,
            "native_partvtkout_report_raw": raw_native_report_binding,
            "native_typed_identity_correction": binding(CORRECTION_SCRIPT, "typed identity correction producer"),
            "native_records": native_records,
        },
        "source": {
            "generated_xml": binding(generated["xml"], "generated XML"),
            "motion_control": binding(generated["motion"], "motion control"),
            "run_out": binding(paths["run_out"], "Run.out"),
            "run_csv": binding(paths["run_csv"], "Run.csv"),
            "runparts": binding(paths["runparts"], "RunPARTs.csv"),
            "gencase_receipt": binding(gencase_receipt, "GenCase receipt"),
            "native_part_files": {
                "count": EXPECTED_FRAMES,
                "first": binding(paths["part_first"], "first native Part"),
                "middle": binding(paths["part_middle"], "middle native Part"),
                "last": binding(paths["part_last"], "last native Part"),
            },
        },
        "native_exclusion_evidence": {
            "report": native_report_binding,
            "raw_report": raw_native_report_binding,
            "row_count": native["partvtkout_exclusions"]["row_count"],
            "NpOut_sum": native["native_timeline"]["NpOut_sum"],
            "NpOutPos_sum": native["native_timeline"]["NpOutPos_sum"],
            "motive_totals": native["partvtkout_exclusions"]["motive_totals"],
            "all_fate_unknown": True,
            "physical_spill_inference": False,
        },
        "fullstate_terminal_binding": {
            "status": "deferred_until_actual_converter_terminal_receipt",
            "conversion_attempt_root": str(conversion_attempt),
            "trajectory_h5": deferred_binding(conversion_attempt / "trajectory.h5", role="full typed lifecycle H5"),
            "conversion_report": deferred_binding(conversion_attempt / "conversion-report.json", role="converter structural/units report"),
            "conversion_receipt": deferred_binding(conversion_attempt / "execution-receipt.json", role="terminal converter receipt"),
            "required_before_labels": True,
            "no_placeholder_hashes_are_qualifying": True,
        },
        "typed_lifecycle_contract": {
            "required_datasets": ["time", "particle_id", "particle_zone", "valid", "position", "velocity", "density", "mass", "pressure", "type", "mk", "initial_type", "initial_mk", "initial_mass"],
            "required_attributes": ["lifecycle_semantics", "typed_identity_source", "units_json", "mass_semantics"],
            "identity_key": ["particle_zone", "particle_id"],
            "initial_typed_axis_is_fixed": True,
            "valid_false_is_native_numerical_unknown": True,
            "birth_reuse_type_change_forbidden": True,
            "full_h5_and_conversion_report_must_be_read_before_QI": True,
        },
        "moving_pose_contract": {
            "producer": str(LABELS),
            "pose_dataset": "rigid_body_state",
            "source": "actual saved Type=1 moving nodes from full H5",
            "control_use": "motion file is an independent prescribed-control comparison",
            "required_fields": ["time", "position", "velocity", "rotation_angle_rad", "translation_m"],
            "initial_aabb_is_insufficient": True,
        },
        "event_label_contract": {
            "operator": {"path": str(EVENT_OPERATOR), "sha256": sha256(EVENT_OPERATOR)},
            "operator_manifest": binding(EVENT_MANIFEST, "event operator manifest"),
            "destination_classes": ["cup_local_top_aperture", "receiver_finite_wall", "tray_finite_wall", "legal_open_domain_exit", "numerical_unknown"],
            "position_only_native_exclusion_cannot_be_destination": True,
            "time_budget_s": 0.0036681953999691376,
            "save_half_width_budget_s": 0.0007336390799938275,
        },
        "qualification_claim": "none",
        "production_claim": "none",
    }
    return owner


def labels_request(background: str, case: dict[str, Any], owner_path: Path, owner: dict[str, Any], paths: dict[str, Path], generated: dict[str, Path], conversion_attempt: Path, static: list[Path]) -> dict[str, Any]:
    case_id = case["case_id"]
    label_attempt = f"labels-{case_id.lower()}-pose-v1-deferred"
    attempt_root = F2_DATA_ROOT / case_id / label_attempt
    future_h5 = conversion_attempt / "trajectory.h5"
    future_report = conversion_attempt / "conversion-report.json"
    future_receipt = conversion_attempt / "execution-receipt.json"
    static_bindings = {str(path): binding(path, "static labels input") for path in static}
    command = [
        str(PYTHON), str(LABELS), "run",
        "--source-trajectory", str(future_h5),
        "--augmented-trajectory", "{attempt_root}/trajectory-with-actual-pose.h5",
        "--owner-metadata", str(owner_path),
        "--generated-xml", str(generated["xml"]),
        "--motion-control", str(generated["motion"]),
        "--run-out", str(paths["run_out"]),
        "--conversion-report", str(future_report),
        "--solver-receipt", str(paths["receipt"]),
        "--gencase-receipt", str(owner["source"]["gencase_receipt"]["path"]),
        "--conversion-receipt", str(future_receipt),
        "--numerical-recipe-hash", str(owner["numerical_recipe_hash"]),
        "--case-id", case_id,
        "--output", "{attempt_root}/f2-v6-labels.h5",
        "--report", "{attempt_root}/f2-v6-observations.json",
        "--pose-report", "{attempt_root}/rigid-body-state.json",
    ]
    # The gencase path is static in the v3 owner lineage only in some old
    # owners.  Keep it explicit and hash-bound in the deferred section so a
    # later binder cannot silently substitute a different GenCase.
    gencase_path = Path(str(owner["source"]["gencase_receipt"]["path"]))
    return {
        "schema": "ds-data-02.f2.rv4eq-fullstate-labels-request.v1-deferred",
        "family_id": "F2",
        "background": background,
        "case_id": case_id,
        "attempt_id": label_attempt,
        "kind": "cpu",
        "cpu_task_kind": "labels",
        "cpu_threads": 4,
        "max_wall_seconds": 1800,
        "estimated_storage_bytes": 80 * 1024**3,
        "status": "deferred_until_terminal_conversion",
        "runnable": False,
        "launch_allowed": False,
        "solver_launch_forbidden": True,
        "gpu_launch": {"family_owner_launch": False, "primary_process_gpu_only": True},
        "command_template": command,
        "cwd": str(FAMILY_ROOT),
        "worktree_root": str(WORKTREE_ROOT),
        "raw_output_root": str(F2_DATA_ROOT),
        "owner_metadata": binding(owner_path, "fullstate owner metadata"),
        "static_input_files": [str(path) for path in static],
        "static_input_sha256": static_bindings,
        "deferred_input_bindings": {
            "trajectory_h5": deferred_binding(future_h5, role="terminal converter trajectory H5"),
            "conversion_report": deferred_binding(future_report, role="terminal converter report"),
            "conversion_receipt": deferred_binding(future_receipt, role="terminal converter receipt"),
        },
        "gencase_binding": {
            "status": "must_be_explicitly_bound_before_dispatch",
            "path": str(gencase_path),
            "sha256": sha256(gencase_path),
        },
        "expected_outputs": {
            "trajectory_with_actual_pose": str(attempt_root / "trajectory-with-actual-pose.h5"),
            "labels": str(attempt_root / "f2-v6-labels.h5"),
            "observations": str(attempt_root / "f2-v6-observations.json"),
            "pose_report": str(attempt_root / "rigid-body-state.json"),
            "receipt": str(attempt_root / "execution-receipt.json"),
        },
        "contract_checks_before_launch": [
            "terminal converter receipt status=completed and returncode=0",
            "conversion report schema/units/typed identity/lifecycle conclusion is actual",
            "H5 required datasets and shape/type/valid semantics are independently checked",
            "source H5 and conversion report hashes are inserted into input_sha256",
            "native PartVTKOut exclusions remain numerical_unknown in labels and observations",
            "no status/within_budget/qualified self-declaration grants Q-I or Q-N",
        ],
        "physical_condition_hash": owner["physical_condition_hash"],
        "numerical_recipe_hash": owner["numerical_recipe_hash"],
        "qualification_claim": "none",
        "production_claim": "none",
    }


def build(output_root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    output_root = output_root.expanduser().resolve()
    native_report = load(CORRECTED_NATIVE_REPORT, "corrected typed native PartVTKOut report")
    manifest = load(V3_MANIFEST, "v3 postprocess manifest")
    owners: list[Path] = []
    requests: list[Path] = []
    cases_out: list[dict[str, Any]] = []
    for background, case in CASES.items():
        v3_owner = require(case["owner"], f"{background} v3 owner")
        conversion_request = require(case["conversion_request"], f"{background} conversion request")
        paths = solver_paths(case["case_id"])
        generated = generated_inputs(case["case_id"])
        native = native_case(native_report, background)
        conversion_attempt = F2_DATA_ROOT / case["case_id"] / case["conversion_attempt_id"]
        owner_value = owner_metadata(background, case, paths, generated, v3_owner, conversion_request, native, conversion_attempt)
        owner_path = output_root / "owner_metadata" / f"{case['case_id']}.owner.v1-deferred.json"
        owner_path.parent.mkdir(parents=True, exist_ok=True)
        owner_path.write_text(json.dumps(owner_value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        static = static_inputs(case, paths, generated, owner_path, conversion_request, native)
        request_value = labels_request(background, case, owner_path, owner_value, paths, generated, conversion_attempt, static)
        request_path = output_root / "labels_requests" / f"{case['case_id']}_labels_request_v1_deferred.json"
        request_path.parent.mkdir(parents=True, exist_ok=True)
        request_path.write_text(json.dumps(request_value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        owners.append(owner_path)
        requests.append(request_path)
        cases_out.append({"background": background, "case_id": case["case_id"], "owner": str(owner_path), "labels_request": str(request_path), "conversion_attempt_root": str(conversion_attempt), "status": "deferred_until_terminal_conversion"})
    output = {
        "schema": SCHEMA,
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "scope_id": "F2_SCOPE_RV4_EQUIVALENT_DP005_PRECHECK_20261002",
        "native_partvtkout_report": binding(CORRECTED_NATIVE_REPORT, "corrected typed native PartVTKOut report"),
        "native_partvtkout_report_raw": binding(NATIVE_REPORT, "immutable raw native PartVTKOut report"),
        "native_typed_identity_correction": binding(CORRECTION_SCRIPT, "typed identity correction producer"),
        "previous_v3_manifest": binding(V3_MANIFEST, "v3 postprocess manifest"),
        "owner_metadata": [{"path": str(path), "sha256": sha256(path)} for path in owners],
        "labels_requests": [{"path": str(path), "sha256": sha256(path)} for path in requests],
        "cases": cases_out,
        "launch_policy": {"solver": False, "conversion": False, "labels": False, "root_binds_terminal_h5_report_receipt_before_labels": True},
        "qualification_claim": "none",
        "production_claim": "none",
    }
    manifest_path = output_root / "fullstate_postprocess_handoff_manifest_v1.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output["manifest"] = {"path": str(manifest_path), "sha256": sha256(manifest_path)}
    manifest_path.write_text(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    result = build(args.output_root)
    print(json.dumps({"schema": result["schema"], "manifest": result["manifest"], "case_count": len(result["cases"]), "status": "deferred_until_terminal_conversion"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
