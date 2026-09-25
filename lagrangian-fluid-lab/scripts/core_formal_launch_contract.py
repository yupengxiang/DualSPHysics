#!/usr/bin/env python3
"""Build a proposal-only contract for the nine Core formal runs.

The contract is a scheduler-facing audit artifact, not a job generator.  It
binds the current source closure, phase/evaluator contracts, output lineage,
and conservative resource estimates while keeping every proposal blocked.
It never launches an optimizer/GPU/solver, creates a formal job spec, or
writes the registry/ledger.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.core_evaluation import PROTOCOL
from scripts.core_formal_planner import (
    CENTERS,
    CHECKPOINT_EVERY,
    HIDDEN,
    LEARNING_RATE,
    MILESTONES,
    MODELS,
    NORMALIZATION_TRANSITIONS,
    REQUIRED_CODE_FILES,
    SEEDS,
    UPDATES,
    VALIDATION_CENTERS,
    VALIDATION_TRANSITIONS,
)
from scripts.core_strict_json import (
    absolute_path_without_following_leaf,
    read_bounded_raw_json,
    strict_json_object,
)


SCHEMA = "core.formal_launch_contract.v1"
CONTRACT_STATUS = "proposal_only_blocked"
RESOURCE_MARGIN = 1.2
OUTPUT_ROOT = "campaigns/core-v1/runtime/formal"


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve(value: str | Path, root: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    return absolute_path_without_following_leaf(path)


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _reference(path: Path, root: Path, *, digest: str | None = None,
               byte_count: int | None = None) -> dict[str, Any]:
    return {
        "path": _relative(path, root),
        "sha256": digest if digest is not None else sha256_file(path),
        "bytes": byte_count if byte_count is not None else path.stat().st_size,
    }


def _load_json(value: str | Path, *, root: Path, role: str) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    path = _resolve(value, root)
    raw = read_bounded_raw_json(path, label=f"{role} {path}")
    payload = strict_json_object(raw, label=f"{role} {path}")
    return payload, path, _reference(
        path, root, digest=sha256_bytes(raw), byte_count=len(raw)
    )


def _code_closure(root: Path, code_root: Path) -> dict[str, Any]:
    files = []
    missing = []
    for relative in REQUIRED_CODE_FILES:
        path = (code_root / relative).resolve()
        if not path.is_file():
            missing.append(relative)
            continue
        files.append({"relative_path": relative, "sha256": sha256_file(path),
                      "bytes": path.stat().st_size})
    closure_sha256 = sha256_bytes(canonical([
        {"relative_path": item["relative_path"], "sha256": item["sha256"]}
        for item in files
    ]).encode())
    return {
        "required_files": list(REQUIRED_CODE_FILES),
        "files": files,
        "missing_files": missing,
        "closure_sha256": closure_sha256,
        "complete": not missing,
        "source_snapshot_policy": "fresh_code_closure_at_formal_admission",
    }


def _snapshot_comparison(current: Mapping[str, Any], snapshot: Mapping[str, Any],
                         reference: Mapping[str, Any]) -> dict[str, Any]:
    rows = snapshot.get("files")
    if not isinstance(rows, list):
        rows = snapshot.get("required_files", [])
    old = {}
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, Mapping):
                name = row.get("relative_path", row.get("path"))
                digest = row.get("sha256")
                if isinstance(name, str) and isinstance(digest, str):
                    old[name] = digest
    now = {item["relative_path"]: item["sha256"] for item in current.get("files", ())}
    mismatch = sorted(name for name in set(old) | set(now) if old.get(name) != now.get(name))
    return {
        "snapshot": dict(reference),
        "snapshot_closure_sha256": snapshot.get("closure_sha256"),
        "current_closure_sha256": current.get("closure_sha256"),
        "mismatch_files": mismatch,
        "matches_current": bool(old) and not mismatch and set(old) == set(now),
        "fresh_snapshot_required": bool(mismatch),
    }


def _resource_estimates(profile: Mapping[str, Any], resource_plan: Mapping[str, Any]) -> dict[str, Any]:
    configurations = profile.get("configurations")
    if not isinstance(configurations, list):
        raise ValueError("resource profile has no configurations")
    declared = resource_plan.get("gpu_peak_mib_declarations", {})
    if not isinstance(declared, Mapping):
        declared = {}
    profile_updates = []
    by_model = {}
    for model in MODELS:
        matches = [row for row in configurations if isinstance(row, Mapping)
                   and model in str(row.get("job_id", "")).lower()]
        if not matches:
            raise ValueError(f"resource profile has no measured row for {model}")
        row = matches[0]
        updates = int(row.get("optimizer_updates", 0))
        wall = float(row.get("wall_seconds_including_startup_normalization_and_checkpoints", 0.0))
        measured_gpu = float(row.get("gpu_peak_mib_measured", 0.0))
        if updates < 1 or not math.isfinite(wall) or wall <= 0 or not math.isfinite(measured_gpu):
            raise ValueError(f"invalid measured resource row for {model}")
        reservation = int(declared.get(model, math.ceil(measured_gpu * RESOURCE_MARGIN)))
        ram = int(resource_plan.get("ram_mib_per_worker", 8192))
        cpu = int(resource_plan.get("cpu_cores_per_worker", 4))
        io_weight = float(resource_plan.get("io_weight_per_worker", 0.25))
        scale = UPDATES / updates
        estimate = wall * scale
        profile_updates.append(updates)
        by_model[model] = {
            "measured_optimizer_updates": updates,
            "measured_wall_seconds": wall,
            "measured_gpu_peak_mib": measured_gpu,
            "reserved_gpu_mib": reservation,
            "reserved_ram_mib": ram,
            "reserved_cpu_cores": cpu,
            "io_weight": io_weight,
            "linear_32000_update_wall_seconds": estimate,
            "linear_32000_update_wall_seconds_with_margin": estimate * RESOURCE_MARGIN,
            "estimate_is_diagnostic_extrapolation": True,
        }
    total_seconds = sum(row["linear_32000_update_wall_seconds_with_margin"] * len(SEEDS)
                        for row in by_model.values())
    concurrent_gpu = sum(row["reserved_gpu_mib"] for row in by_model.values())
    concurrent_ram = sum(row["reserved_ram_mib"] for row in by_model.values())
    concurrent_cpu = sum(row["reserved_cpu_cores"] for row in by_model.values())
    return {
        "profile_updates": sorted(set(profile_updates)),
        "models": by_model,
        "resource_margin": RESOURCE_MARGIN,
        "total_proposed_gpu_hours_with_margin": total_seconds / 3600.0,
        "all_three_model_types_concurrent_reservation": {
            "gpu_mib": concurrent_gpu,
            "ram_mib": concurrent_ram,
            "cpu_cores": concurrent_cpu,
        },
        "capacity_claim": "diagnostic extrapolation only; no 32000-update capacity proof",
        "same_card_concurrency": {
            "allowed": False,
            "max_workers_per_card": 1,
            "reason": "16-update profiles are single-worker measurements; no live free-memory/PSI admission evidence proves co-location",
            "required_live_observations": [
                "free_cuda_memory_mib", "free_host_ram_mib", "memory_psi", "io_psi",
                "active_same_card_processes", "reserved_sum_with_safety_margin",
            ],
        },
    }


def _run_matrix(resources: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for model in MODELS:
        for seed in SEEDS:
            run_id = f"{model}-seed{seed}"
            run_root = f"{OUTPUT_ROOT}/{run_id}"
            model_resource = resources["models"][model]
            rows.append({
                "proposal_id": run_id,
                "run_id": run_id,
                "model": model,
                "seed": seed,
                "status": "blocked_by_formal_gates",
                "launch_allowed": False,
                "formal_job": False,
                "training": {
                    "updates": UPDATES,
                    "centers_per_update": CENTERS,
                    "hidden": HIDDEN,
                    "learning_rate": LEARNING_RATE,
                    "normalization_transitions": NORMALIZATION_TRANSITIONS,
                    "validation_transitions": VALIDATION_TRANSITIONS,
                    "validation_centers": VALIDATION_CENTERS,
                    "checkpoint_every": CHECKPOINT_EVERY,
                    "evaluate_milestones": True,
                    "test_included": False,
                },
                "resources": dict(model_resource),
                "output_lineage": {
                    "run_root": run_root,
                    "training_receipt": f"{run_root}/training.json",
                    "progress_sidecar": f"{run_root}/training-progress.json",
                    "final_checkpoint": f"{run_root}/checkpoints/model.pt",
                    "milestone_checkpoints": [
                        f"{run_root}/checkpoints/model.step-{update:08d}.pt"
                        for update in MILESTONES
                    ],
                    "milestone_evaluations": [
                        f"{run_root}/checkpoints/model.step-{update:08d}.evaluation.json"
                        for update in MILESTONES
                    ],
                    "run_id_binding": run_id,
                    "model_seed_binding": {"model": model, "seed": seed},
                    "source_snapshot_binding_required": True,
                    "manifest_sha256_binding_required": True,
                },
                "phase_dependencies": {
                    "verify": "phase-plan and formal input audit pass",
                    "inspect": "source manifest, family/validation shape, and input hashes pass",
                    "train": "formal admission ready; exactly one fresh run_id/model/seed",
                    "rollout": "training receipt and all four milestone checkpoints verified",
                    "evaluate": "four validation milestone reports; fixed denominator; select_checkpoint",
                    "reproduce": "selected checkpoint on a distinct host with source/output hashes",
                },
                "checkpoint_selection": {
                    "module": "scripts/core_evaluation.py",
                    "function": "select_checkpoint",
                    "milestones": list(MILESTONES),
                    "split": "validation",
                    "requires_all_milestones": True,
                    "test_included": False,
                },
                "failure_denominator": {
                    "source": "registered time axis; expected_frames=len(time)-1",
                    "missing_execution_penalty": 1.0,
                    "failed_case_retained": True,
                },
            })
    return rows


def build_contract(*, data_root: str | Path, readiness: str | Path,
                    phase_plan: str | Path, resource_profile: str | Path,
                    resource_plan: str | Path, source_closure: str | Path | None = None,
                    code_root: str | Path | None = None) -> dict[str, Any]:
    root = Path(data_root).expanduser().resolve()
    readiness_payload, _, readiness_ref = _load_json(readiness, root=root, role="formal readiness")
    phase_payload, _, phase_ref = _load_json(phase_plan, root=root, role="phase plan")
    profile_payload, _, profile_ref = _load_json(resource_profile, root=root, role="resource profile")
    plan_payload, _, plan_ref = _load_json(resource_plan, root=root, role="resource plan")
    code = Path(code_root).expanduser().resolve() if code_root is not None else root
    closure = _code_closure(root, code)
    snapshot = None
    if source_closure is not None:
        snapshot_payload, _, snapshot_ref = _load_json(source_closure, root=root, role="source closure")
        snapshot = _snapshot_comparison(closure, snapshot_payload, snapshot_ref)

    phase_contract = readiness_payload.get("phase_plan", {}).get("contract_passed") is True
    evaluator_contract = readiness_payload.get("evaluator_contract", {}).get("contract_passed") is True
    readiness_checks = readiness_payload.get("checks")
    readiness_checks = readiness_checks if isinstance(readiness_checks, Mapping) else {}
    gate = {
        "formal_readiness": readiness_payload.get("status") == "ready",
        "third_t1_family": readiness_checks.get("third_t1_family") is True,
        "validation_12_case": readiness_checks.get("validation_denominator") is True,
        "formal_runs_9": readiness_checks.get("formal_run_denominator") is True,
        "material_case_runs_288": readiness_checks.get("material_case_run_denominator") is True,
        "phase_plan_denominator": phase_contract,
        "failure_penalty": evaluator_contract,
        "source_closure_complete": closure["complete"],
        # A source closure is an admission binding, not an optional hint.  An
        # omitted snapshot must remain blocked even when the live closure is
        # internally complete; otherwise a future all-green gate evaluation
        # could authorize formal work without a persisted source identity.
        "fresh_source_closure": snapshot is not None and snapshot.get("matches_current") is True,
        "same_card_concurrency": False,
        "output_checkpoint_lineage_contract": True,
        "no_formal_job_emission": True,
    }
    resources = _resource_estimates(profile_payload, plan_payload)
    matrix = _run_matrix(resources)
    blockers = []
    if not gate["formal_readiness"]:
        blockers.append("formal readiness artifact is blocked")
    if not gate["third_t1_family"]:
        blockers.append("third T1 family gate is not met")
    if not gate["validation_12_case"]:
        blockers.append("12-case validation denominator gate is not met")
    if not gate["formal_runs_9"]:
        blockers.append("9 formal model-seed runs are not complete")
    if not gate["material_case_runs_288"]:
        blockers.append("288 material case-run target remains incomplete")
    if not gate["phase_plan_denominator"]:
        blockers.append("phase-plan denominator contract is not passed")
    if not gate["failure_penalty"]:
        blockers.append("evaluator failure penalty contract is not passed")
    if not gate["source_closure_complete"]:
        blockers.append("current formal source closure is incomplete")
    if not gate["fresh_source_closure"]:
        blockers.append("existing source closure is stale; fresh closure must be admitted")
    blockers.append("same-card concurrency is unproven and remains disabled")
    return {
        "schema": SCHEMA,
        "record_id": "core-formal-launch-contract-20260921",
        "status": CONTRACT_STATUS,
        "proposal_only": True,
        "formal_job_count": 0,
        "required_formal_job_count": len(MODELS) * len(SEEDS),
        "launch_allowed": False,
        "data_root": str(root),
        "inputs": {
            "readiness": readiness_ref,
            "phase_plan": phase_ref,
            "resource_profile": profile_ref,
            "resource_plan": plan_ref,
            "source_closure": snapshot,
        },
        "source_closure": closure,
        "gate_evaluation": gate,
        "blockers": blockers,
        "run_matrix": matrix,
        "resource_estimates": resources,
        "protocol": {
            "models": list(MODELS),
            "seeds": list(SEEDS),
            "updates": UPDATES,
            "checkpoint_milestones": list(MILESTONES),
            "validation_split": PROTOCOL["selection_split"],
            "fixed_denominator": PROTOCOL["case_denominator"],
            "missing_failed_nonfinite_frame_score": PROTOCOL["missing_failed_nonfinite_frame_score"],
            "selection": PROTOCOL["selection"],
            "test_included": False,
        },
        "execution_constraints": {
            "read_only": True,
            "formal_job_specs_written": False,
            "formal_jobs_submitted": False,
            "formal_runs_started": 0,
            "optimizer_started": False,
            "gpu_started": False,
            "solver_started": False,
            "registry_written": False,
            "ledger_written": False,
            "trajectory_state_frames_read": 0,
            "future_state_inputs": False,
        },
        "admission_next_step": (
            "after all gates pass, regenerate a fresh source closure and invoke the existing "
            "core_formal_planner; this proposal contract itself never emits or submits jobs"
        ),
    }


def write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True,
                                    ensure_ascii=False, allow_nan=False) + "\n",
                          encoding="utf-8")
    temporary.replace(target)


def write_sha256(path: str | Path, *, source: str | Path) -> None:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    source_path = Path(source).expanduser().resolve()
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(f"{sha256_file(source_path)}  {source_path.name}\n", encoding="utf-8")
    temporary.replace(target)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--readiness", type=Path, required=True)
    parser.add_argument("--phase-plan", type=Path, required=True)
    parser.add_argument("--resource-profile", type=Path, required=True)
    parser.add_argument("--resource-plan", type=Path, required=True)
    parser.add_argument("--source-closure", type=Path)
    parser.add_argument("--code-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sha256-output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    contract = build_contract(
        data_root=args.data_root,
        readiness=args.readiness,
        phase_plan=args.phase_plan,
        resource_profile=args.resource_profile,
        resource_plan=args.resource_plan,
        source_closure=args.source_closure,
        code_root=args.code_root,
    )
    write_json(args.output, contract)
    if args.sha256_output is not None:
        write_sha256(args.sha256_output, source=args.output)
    print(json.dumps({
        "status": contract["status"],
        "formal_job_count": contract["formal_job_count"],
        "required_formal_job_count": contract["required_formal_job_count"],
        "proposal_rows": len(contract["run_matrix"]),
        "launch_allowed": contract["launch_allowed"],
        "blockers": contract["blockers"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
