#!/usr/bin/env python3
"""Run an evidence-bound F2 v6 label stage from an actual full-state H5.

The reviewed direct converter writes the particle state but does not always
carry the moving-body pose.  This additive stage therefore copies the source
H5 to a new attempt-local file, fits ``rigid_body_state`` from the saved native
Type=1 moving nodes using the copied mvrotfile only as the sign/control
comparison, and then runs the independent v6 local-z opening operator.  The
source H5 is never opened for write and never replaced.

This script is a CPU labels-stage producer.  It does not launch a solver,
GenCase, GPU job, or qualification decision.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
from typing import Any


F2_ROOT = Path(__file__).resolve().parent
WORKTREE_ROOT = F2_ROOT.parents[4]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
INTEGRATION_LAB = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab")
POSE_HELPER = INTEGRATION_LAB / "scripts/ds_data02_convert.py"
V6_SCRIPT = F2_ROOT / "f2_handoff_20261002_event_semantics_v6.py"
V6_MANIFEST = F2_ROOT / "handoff_20261002/event_semantics_v6/operator_manifest.json"
QUALITY_CONTRACT = F2_ROOT / "quality_contract.json"
EVENT_DEFINITIONS = F2_ROOT / "event_definitions.json"
SAVE_PLAN = F2_ROOT / "integration_save_plan.json"
CASE_REGISTRY = F2_ROOT / "case_registry.jsonl"
RUNTIME_V2 = INTEGRATION_LAB / "scripts/ds_data02_runtime_v2.py"


class LabelStageError(RuntimeError):
    """Raised when an evidence-bound labels input is incomplete."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(path: Path, label: str) -> Path:
    path = path.resolve()
    if not path.is_file():
        raise LabelStageError(f"{label} is missing: {path}")
    return path


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise LabelStageError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_times_from_h5(path: Path) -> list[float]:
    import h5py
    import numpy as np

    with h5py.File(path, "r") as handle:
        if "time" not in handle:
            raise LabelStageError(f"source H5 has no time dataset: {path}")
        times = np.asarray(handle["time"][:], dtype=np.float64)
    if len(times) < 2 or not np.isfinite(times).all() or not np.all(np.diff(times) > 0):
        raise LabelStageError("source H5 time axis is not finite and strictly increasing")
    return [float(value) for value in times]


def case_nmoving(run_out: Path) -> int:
    match = re.search(r"CaseNmoving\s*=\s*([0-9,]+)", run_out.read_text(errors="replace"), re.IGNORECASE)
    if match is None:
        raise LabelStageError(f"Run.out has no CaseNmoving: {run_out}")
    value = int(match.group(1).replace(",", ""))
    if value <= 0:
        raise LabelStageError(f"Run.out reports no moving boundary nodes: {value}")
    return value


def augment_pose(*, source: Path, augmented: Path, generated_xml: Path,
                 motion: Path, run_out: Path, pose_report: Path,
                 conversion_report: Path, solver_receipt: Path,
                 gencase_receipt: Path, owner_metadata: Path) -> dict[str, Any]:
    """Copy the source H5 and append the actual saved moving-node pose."""
    source = require_file(source, "source trajectory H5")
    generated_xml = require_file(generated_xml, "generated XML")
    motion = require_file(motion, "copied motion control")
    run_out = require_file(run_out, "solver Run.out")
    conversion_report = require_file(conversion_report, "conversion report")
    solver_receipt = require_file(solver_receipt, "solver receipt")
    gencase_receipt = require_file(gencase_receipt, "GenCase receipt")
    owner_metadata = require_file(owner_metadata, "owner metadata")
    augmented = augmented.resolve()
    if augmented == source:
        raise LabelStageError("refusing to modify source trajectory in place")
    if augmented.exists():
        raise LabelStageError(f"refusing to overwrite augmented trajectory: {augmented}")
    augmented.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, augmented)

    pose_helper = load_module(POSE_HELPER, "ds_data02_actual_pose_helper")
    motion_spec = pose_helper._parse_motion_control(motion, generated_xml)
    if motion_spec is None:
        raise LabelStageError("copied motion control is not a rotational mvrotfile")
    times = run_times_from_h5(augmented)
    pose = pose_helper._write_rigid_body_state(
        augmented,
        {"motion_control_spec": motion_spec, "population": {"case_nmoving": case_nmoving(run_out)}},
        times,
    )
    if pose.get("status") != "pass":
        raise LabelStageError(f"actual moving-node pose fit failed: {pose}")
    report = {
        "schema": "ds-data-02.f2.actual-moving-pose.v1",
        "status": "actual_saved_moving_node_pose_complete",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_trajectory": {"path": str(source), "sha256": sha256(source)},
        "augmented_trajectory": {"path": str(augmented), "sha256": sha256(augmented)},
        "generated_xml": {"path": str(generated_xml), "sha256": sha256(generated_xml)},
        "motion_control": {"path": str(motion), "sha256": sha256(motion)},
        "run_out": {"path": str(run_out), "sha256": sha256(run_out)},
        "conversion_report": {"path": str(conversion_report), "sha256": sha256(conversion_report)},
        "solver_receipt": {"path": str(solver_receipt), "sha256": sha256(solver_receipt)},
        "gencase_receipt": {"path": str(gencase_receipt), "sha256": sha256(gencase_receipt)},
        "owner_metadata": {"path": str(owner_metadata), "sha256": sha256(owner_metadata)},
        "pose": pose,
        "claim": "pose and labels evidence only; no Q-I/Q-N/production decision",
    }
    pose_report = pose_report.resolve()
    pose_report.parent.mkdir(parents=True, exist_ok=True)
    pose_report.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report["pose_report"] = {"path": str(pose_report), "sha256": sha256(pose_report)}
    return report


def run_labels(*, source: Path, augmented: Path, owner_metadata: Path,
               generated_xml: Path, numerical_hash: str, case_id: str,
               output: Path, report: Path, pose_report: Path,
               conversion_report: Path, solver_receipt: Path,
               gencase_receipt: Path, motion: Path, run_out: Path) -> dict[str, Any]:
    pose = augment_pose(source=source, augmented=augmented, generated_xml=generated_xml,
                        motion=motion, run_out=run_out, pose_report=pose_report,
                        conversion_report=conversion_report, solver_receipt=solver_receipt,
                        gencase_receipt=gencase_receipt, owner_metadata=owner_metadata)
    v6 = load_module(V6_SCRIPT, "f2_event_semantics_v6_labels")
    observed = v6.observe(
        trajectory=augmented,
        owner_metadata=owner_metadata,
        output=output.resolve(),
        report=report.resolve(),
        definition_override=generated_xml.resolve(),
        numerical_recipe_hash_override=str(numerical_hash),
        case_id_override=str(case_id),
    )
    return {
        "schema": "ds-data-02.f2.v6-label-stage.v1",
        "status": "completed",
        "pose_report": pose["pose_report"],
        "augmented_trajectory": {"path": str(augmented.resolve()), "sha256": sha256(augmented)},
        "labels": {"path": str(output.resolve()), "sha256": sha256(output)},
        "observations": {"path": str(report.resolve()), "sha256": sha256(report)},
        "v6_operator_sha256": observed["operator"]["sha256"],
        "q_n_status": "not_assessed",
        "production_eligibility": "not_evaluated",
    }


def bindings(paths: list[Path]) -> dict[str, dict[str, str]]:
    return {str(path.resolve()): {"path": str(path.resolve()), "sha256": sha256(path)} for path in paths}


def make_request(*, source: Path, owner_metadata: Path, generated_xml: Path,
                 motion: Path, run_out: Path, conversion_report: Path,
                 solver_receipt: Path, gencase_receipt: Path,
                 conversion_receipt: Path, numerical_hash: str, case_id: str,
                 request_path: Path) -> dict[str, Any]:
    source = require_file(source, "source trajectory H5")
    owner_metadata = require_file(owner_metadata, "owner metadata")
    generated_xml = require_file(generated_xml, "generated XML")
    motion = require_file(motion, "copied motion control")
    run_out = require_file(run_out, "solver Run.out")
    conversion_report = require_file(conversion_report, "conversion report")
    solver_receipt = require_file(solver_receipt, "solver receipt")
    gencase_receipt = require_file(gencase_receipt, "GenCase receipt")
    conversion_receipt = require_file(conversion_receipt, "conversion receipt")
    attempt_id = "labels-f2h10v2-center-v1-coarse-rv4d1-baseline-save001-event-semantics-v6-pose-v1"
    attempt_root = DATA_ROOT / "families/F2/F2H10V2_CENTER_V1_COARSE_RV4D1_BASELINE_SAVE001" / attempt_id
    output = attempt_root / "f2-v6-labels.h5"
    report = attempt_root / "f2-v6-observations.json"
    augmented = attempt_root / "trajectory-with-actual-pose.h5"
    pose_report = attempt_root / "rigid-body-state.json"
    python = WORKTREE_ROOT / "lagrangian-fluid-lab/.venv/bin/python"
    input_paths = [
        Path(__file__), V6_SCRIPT, V6_MANIFEST, POSE_HELPER, RUNTIME_V2,
        QUALITY_CONTRACT, EVENT_DEFINITIONS, SAVE_PLAN, CASE_REGISTRY,
        source, owner_metadata, generated_xml, motion, run_out,
        conversion_report, solver_receipt, gencase_receipt, conversion_receipt,
    ]
    input_paths = [require_file(path, "labels request input") for path in input_paths]
    request = {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": "F2",
        "case_id": case_id,
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": "labels",
        "cpu_threads": 4,
        "max_wall_seconds": 1200,
        "estimated_storage_bytes": 3 * 1024**3,
        "command": [
            str(python), str(Path(__file__).resolve()), "run",
            "--source-trajectory", str(source), "--augmented-trajectory", "{attempt_root}/trajectory-with-actual-pose.h5",
            "--owner-metadata", str(owner_metadata), "--generated-xml", str(generated_xml),
            "--motion-control", str(motion), "--run-out", str(run_out),
            "--conversion-report", str(conversion_report), "--solver-receipt", str(solver_receipt),
            "--gencase-receipt", str(gencase_receipt), "--conversion-receipt", str(conversion_receipt),
            "--numerical-recipe-hash", str(numerical_hash), "--case-id", str(case_id),
            "--output", "{attempt_root}/f2-v6-labels.h5", "--report", "{attempt_root}/f2-v6-observations.json",
            "--pose-report", "{attempt_root}/rigid-body-state.json",
        ],
        "cwd": str(F2_ROOT.resolve()),
        "raw_output_root": str((DATA_ROOT / "families/F2/F2H10V2_CENTER_V1_COARSE_RV4D1_BASELINE_SAVE001").resolve()),
        "worktree_root": str(WORKTREE_ROOT.resolve()),
        "input_files": [str(path) for path in input_paths],
        "source_bindings": bindings(input_paths),
        "source_h5": {"path": str(source), "sha256": sha256(source)},
        "conversion_receipt": {"path": str(conversion_receipt), "sha256": sha256(conversion_receipt)},
        "conversion_report": {"path": str(conversion_report), "sha256": sha256(conversion_report)},
        "generated_xml": {"path": str(generated_xml), "sha256": sha256(generated_xml)},
        "motion_control": {"path": str(motion), "sha256": sha256(motion)},
        "physical_condition_hash": "45c579bd9fa7a4878fcd25d0e0aa6dedf6da8c4cd77cd85e0d05b928ab8b6a43",
        "numerical_recipe_hash": str(numerical_hash),
        "expected_outputs": {
            "receipt": str(attempt_root / "execution-receipt.json"),
            "augmented_trajectory": str(augmented), "pose_report": str(pose_report),
            "labels": str(output), "observations": str(report),
        },
        "solver_launch_forbidden": True,
        "gpu_launch": {"family_owner_launch": False, "primary_process_gpu_only": True},
        "request_note": "CPU-only additive v6 labels from completed v5-002 full-state H5; source H5 is immutable, pose is fitted from actual saved moving nodes, and Q-N/production remain pending.",
    }
    request_path = request_path.resolve()
    if request_path.exists():
        raise LabelStageError(f"refusing to overwrite request: {request_path}")
    request_path.parent.mkdir(parents=True, exist_ok=True)
    request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return request


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    req = sub.add_parser("make-request")
    req.add_argument("--source-trajectory", type=Path, required=True)
    req.add_argument("--owner-metadata", type=Path, required=True)
    req.add_argument("--generated-xml", type=Path, required=True)
    req.add_argument("--motion-control", type=Path, required=True)
    req.add_argument("--run-out", type=Path, required=True)
    req.add_argument("--conversion-report", type=Path, required=True)
    req.add_argument("--solver-receipt", type=Path, required=True)
    req.add_argument("--gencase-receipt", type=Path, required=True)
    req.add_argument("--conversion-receipt", type=Path, required=True)
    req.add_argument("--numerical-recipe-hash", required=True)
    req.add_argument("--case-id", required=True)
    req.add_argument("--request", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("--source-trajectory", type=Path, required=True)
    run.add_argument("--augmented-trajectory", type=Path, required=True)
    run.add_argument("--owner-metadata", type=Path, required=True)
    run.add_argument("--generated-xml", type=Path, required=True)
    run.add_argument("--motion-control", type=Path, required=True)
    run.add_argument("--run-out", type=Path, required=True)
    run.add_argument("--conversion-report", type=Path, required=True)
    run.add_argument("--solver-receipt", type=Path, required=True)
    run.add_argument("--gencase-receipt", type=Path, required=True)
    run.add_argument("--conversion-receipt", type=Path, required=True)
    run.add_argument("--numerical-recipe-hash", required=True)
    run.add_argument("--case-id", required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--report", type=Path, required=True)
    run.add_argument("--pose-report", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "make-request":
            request = make_request(
                source=args.source_trajectory, owner_metadata=args.owner_metadata,
                generated_xml=args.generated_xml, motion=args.motion_control,
                run_out=args.run_out, conversion_report=args.conversion_report,
                solver_receipt=args.solver_receipt, gencase_receipt=args.gencase_receipt,
                conversion_receipt=args.conversion_receipt, numerical_hash=args.numerical_recipe_hash,
                case_id=args.case_id, request_path=args.request,
            )
            print(json.dumps({"status": "written", "request": str(args.request.resolve()), "input_count": len(request["input_files"])}, indent=2))
        else:
            result = run_labels(
                source=args.source_trajectory, augmented=args.augmented_trajectory,
                owner_metadata=args.owner_metadata, generated_xml=args.generated_xml,
                numerical_hash=args.numerical_recipe_hash, case_id=args.case_id,
                output=args.output, report=args.report, pose_report=args.pose_report,
                conversion_report=args.conversion_report, solver_receipt=args.solver_receipt,
                gencase_receipt=args.gencase_receipt, motion=args.motion_control,
                run_out=args.run_out,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (LabelStageError, OSError, ValueError, KeyError, RuntimeError) as error:
        print(f"f2_v6_labels: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
