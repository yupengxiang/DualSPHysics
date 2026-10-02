#!/usr/bin/env python3
"""Freeze the additive CPU request for the DP005 native exclusion diagnostic."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


F2_ROOT = Path(__file__).resolve().parent
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
INTEGRATION_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
RUNTIME_V2 = INTEGRATION_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
PARTVTKOUT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTKOut_linux64")
DIAGNOSTIC = F2_ROOT / "f2_handoff_20261002_dp005_native_diagnostic_v1.py"
CHECKPOINT = INTEGRATION_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261002/F2_RV4_NATIVE_EXECUTION_CHECKPOINT_004.json"
OUTPUT_DIR = F2_ROOT / "handoff_20261002/postsolver_v7/dp005_native_diagnostic_v2"
MANIFEST = OUTPUT_DIR / "dp005_native_diagnostic_v2_manifest.json"
REQUEST = OUTPUT_DIR / "dp005_native_diagnostic_v2_request.json"
ATTEMPT_ID = "diagnostic-f2-dp005-repair01-native-exclusions-v2"
CASE_ID = "F2_COMM4_DP005_REPAIR01_NATIVE_EXCLUSION_DIAGNOSTIC"


CASES = [
    {
        "case_id": "F2_COMM4_CENTER_V1_DP005_REPAIR01_MACRO_SAVE010",
        "background": "center_catch",
        "physical_case_id": "F2_COMM4_CENTER_V1",
        "dp_m": 0.005,
        "generated_xml": DATA_ROOT / "families/F2/F2_COMM4_CENTER_V1_DP005/gencase-f2-f2-comm4-center-v1-dp005-gridaligned-v2/F2_COMM4_CENTER_V1_DP005.xml",
        "motion": DATA_ROOT / "families/F2/F2_COMM4_CENTER_V1_DP005/gencase-f2-f2-comm4-center-v1-dp005-gridaligned-v2/F2_COMM4_CENTER_V1_DP005_motion.dat",
        "gencase_receipt": DATA_ROOT / "families/F2/F2_COMM4_CENTER_V1_DP005/gencase-f2-f2-comm4-center-v1-dp005-gridaligned-v2/execution-receipt.json",
        "solver_receipt": DATA_ROOT / "families/F2/F2_COMM4_CENTER_V1_DP005_REPAIR01_MACRO_SAVE010/qualification-f2_comm4_center_v1_dp005_repair01_macro_save010-native-fullstate-v1/execution-receipt.json",
        "runparts": DATA_ROOT / "families/F2/F2_COMM4_CENTER_V1_DP005_REPAIR01_MACRO_SAVE010/qualification-f2_comm4_center_v1_dp005_repair01_macro_save010-native-fullstate-v1/solver_output/RunPARTs.csv",
        "data_dir": DATA_ROOT / "families/F2/F2_COMM4_CENTER_V1_DP005_REPAIR01_MACRO_SAVE010/qualification-f2_comm4_center_v1_dp005_repair01_macro_save010-native-fullstate-v1/solver_output/data",
        "owner_metadata": F2_ROOT / "handoff_20261002/postsolver_v7/owner_metadata/F2_COMM4_CENTER_V1_DP005_REPAIR01_MACRO_SAVE010.generator.v7.metadata.json",
        "rv4": {
            "case_id": "F2H10V2_CENTER_V1_MEDIUM_RV4D1_BASELINE_SAVE001",
            "generated_xml": INTEGRATION_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261002/root_rv4_launch_001/staged_inputs/F2H10V2_CENTER_V1_MEDIUM_RV4D1_BASELINE_SAVE001/F2H10V2_CENTER_V1_MEDIUM_RV4D1_BASELINE_SAVE001.xml",
            "motion": INTEGRATION_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261002/root_rv4_launch_001/staged_inputs/F2H10V2_CENTER_V1_MEDIUM_RV4D1_BASELINE_SAVE001/F2H10V2_CENTER_V1_MEDIUM_motion.dat",
            "owner_metadata": F2_ROOT / "handoff_20261002/postsolver_v7/owner_metadata/F2H10V2_CENTER_V1_MEDIUM_RV4D1_BASELINE_SAVE001.generator.v7.metadata.json",
            "conversion_report": DATA_ROOT / "families/F2/F2H10V2_CENTER_V1_MEDIUM_RV4D1_BASELINE_SAVE001/conversion-f2h10v2_center_v1_medium_rv4d1_baseline_save001-fullstate-v5-002/conversion-report.json",
        },
    },
    {
        "case_id": "F2_COMM4_OFFSET_V1_DP005_REPAIR01_MACRO_SAVE010",
        "background": "offset_spill",
        "physical_case_id": "F2_COMM4_OFFSET_V1",
        "dp_m": 0.005,
        "generated_xml": DATA_ROOT / "families/F2/F2_COMM4_OFFSET_V1_DP005/gencase-f2-f2-comm4-offset-v1-dp005-gridaligned-v2/F2_COMM4_OFFSET_V1_DP005.xml",
        "motion": DATA_ROOT / "families/F2/F2_COMM4_OFFSET_V1_DP005/gencase-f2-f2-comm4-offset-v1-dp005-gridaligned-v2/F2_COMM4_OFFSET_V1_DP005_motion.dat",
        "gencase_receipt": DATA_ROOT / "families/F2/F2_COMM4_OFFSET_V1_DP005/gencase-f2-f2-comm4-offset-v1-dp005-gridaligned-v2/execution-receipt.json",
        "solver_receipt": DATA_ROOT / "families/F2/F2_COMM4_OFFSET_V1_DP005_REPAIR01_MACRO_SAVE010/qualification-f2_comm4_offset_v1_dp005_repair01_macro_save010-native-fullstate-v1/execution-receipt.json",
        "runparts": DATA_ROOT / "families/F2/F2_COMM4_OFFSET_V1_DP005_REPAIR01_MACRO_SAVE010/qualification-f2_comm4_offset_v1_dp005_repair01_macro_save010-native-fullstate-v1/solver_output/RunPARTs.csv",
        "data_dir": DATA_ROOT / "families/F2/F2_COMM4_OFFSET_V1_DP005_REPAIR01_MACRO_SAVE010/qualification-f2_comm4_offset_v1_dp005_repair01_macro_save010-native-fullstate-v1/solver_output/data",
        "owner_metadata": F2_ROOT / "handoff_20261002/postsolver_v7/owner_metadata/F2_COMM4_OFFSET_V1_DP005_REPAIR01_MACRO_SAVE010.generator.v7.metadata.json",
        "rv4": {
            "case_id": "F2H10V2_OFFSET_V1_COARSE_RV4D1_BASELINE_SAVE001",
            "generated_xml": INTEGRATION_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261002/root_rv4_launch_001/staged_inputs/F2H10V2_OFFSET_V1_COARSE_RV4D1_BASELINE_SAVE001/F2H10V2_OFFSET_V1_COARSE_RV4D1_BASELINE_SAVE001.xml",
            "motion": INTEGRATION_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261002/root_rv4_launch_001/staged_inputs/F2H10V2_OFFSET_V1_COARSE_RV4D1_BASELINE_SAVE001/F2H10V2_OFFSET_V1_COARSE_motion.dat",
            "owner_metadata": F2_ROOT / "handoff_20261002/postsolver_v7/owner_metadata/F2H10V2_OFFSET_V1_COARSE_RV4D1_BASELINE_SAVE001.generator.v7.metadata.json",
            "conversion_report": DATA_ROOT / "families/F2/F2H10V2_OFFSET_V1_COARSE_RV4D1_BASELINE_SAVE001/conversion-f2h10v2_offset_v1_coarse_rv4d1_baseline_save001-fullstate-v5-002/conversion-report.json",
        },
    },
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    return path


def jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value.resolve())
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [jsonable(item) for item in value]
    return value


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(jsonable(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def all_inputs() -> list[Path]:
    paths: list[Path] = [DIAGNOSTIC, RUNTIME_V2, PARTVTKOUT, CHECKPOINT]
    for case in CASES:
        paths.extend([case["generated_xml"], case["motion"], case["gencase_receipt"], case["solver_receipt"], case["runparts"], case["data_dir"] / "PartOut_000.obi4", case["owner_metadata"]])
        rv4 = case["rv4"]
        paths.extend([rv4["generated_xml"], rv4["motion"], rv4["owner_metadata"], rv4["conversion_report"]])
    return [require(path, "DP005 diagnostic input") for path in paths]


def make() -> tuple[Path, Path]:
    inputs = all_inputs()
    bindings = {str(path): {"path": str(path), "sha256": sha256(path)} for path in inputs}
    manifest = {
        "schema": "ds-data-02.f2.dp005-native-diagnostic-input.v1",
        "family_id": "F2",
        "diagnostic_id": "F2_DP005_NATIVE_EXCLUSION_DIAGNOSTIC_V1",
        "cases": jsonable(CASES),
        "runparts_semantics": "PartOut is a native saved-part index; time is read from the bound RunPARTs.csv row, and every Motive remains numerical unknown.",
        "mother_comparison": {
            "rv4_comparison_is_measured": True,
            "boundary_boxes_exclude_fluid_population_commands": True,
            "motion_values_are_compared_after_parsing": True,
            "qualification_or_production_claim": "none",
        },
        "source_bindings": bindings,
    }
    write(MANIFEST, manifest)
    attempt_root = DATA_ROOT / "families/F2" / CASE_ID / ATTEMPT_ID
    python = F2_ROOT.parents[4] / "lagrangian-fluid-lab/.venv/bin/python"
    request_inputs = inputs + [MANIFEST]
    request_bindings = {str(path): {"path": str(path), "sha256": sha256(path)} for path in request_inputs}
    request = {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": "F2",
        "case_id": CASE_ID,
        "attempt_id": ATTEMPT_ID,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 4,
        "max_wall_seconds": 600,
        "estimated_storage_bytes": 256 * 1024**2,
        "command": [str(python), str(DIAGNOSTIC), "--manifest", str(MANIFEST), "--partvtkout", str(PARTVTKOUT), "--output", "{attempt_root}/dp005-native-diagnostic.json"],
        "cwd": str(F2_ROOT),
        "raw_output_root": str(DATA_ROOT / "families/F2"),
        "worktree_root": str(F2_ROOT.parents[4]),
        "input_files": [str(path) for path in request_inputs],
        "source_bindings": request_bindings,
        "expected_outputs": {
            "receipt": str(attempt_root / "execution-receipt.json"),
            "report": str(attempt_root / "dp005-native-diagnostic.json"),
            "partvtkout_artifacts": str(attempt_root / "artifacts/partvtkout"),
            "enriched_records": str(attempt_root / "artifacts/records"),
        },
        "source_cases": [
            {"case_id": case["case_id"], "physical_case_id": case["physical_case_id"], "dp_m": case["dp_m"], "status": "completed_native_solver_bound"}
            for case in CASES
        ],
        "solver_launch_forbidden": True,
        "gpu_launch": {"family_owner_launch": False, "primary_process_gpu_only": True},
        "status": "ready_for_root_shared_cpu_diagnostic",
        "request_note": "CPU-only official PartVTKOut export of both completed DP005 native PartOut ledgers, including all excluded Idp/PartOut/time/position/Motive records and measured RV4 geometry/control comparison. No conversion, solver, GPU, Q-I, Q-N, or production claim.",
        "qualification_claim": "none",
        "production_claim": "none",
    }
    write(REQUEST, request)
    return MANIFEST, REQUEST


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--request", type=Path, default=REQUEST)
    args = parser.parse_args()
    manifest, request = make()
    if args.manifest.resolve() != manifest.resolve() or args.request.resolve() != request.resolve():
        # Keep the producer deterministic while permitting a review copy.
        write(args.manifest.resolve(), json.loads(manifest.read_text(encoding="utf-8")))
        write(args.request.resolve(), json.loads(request.read_text(encoding="utf-8")))
    print(json.dumps({"manifest": str(manifest), "manifest_sha256": sha256(manifest), "request": str(request), "request_sha256": sha256(request), "status": "ready_for_root_shared_cpu_diagnostic"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
