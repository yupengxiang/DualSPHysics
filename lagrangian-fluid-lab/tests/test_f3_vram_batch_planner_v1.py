"""Synthetic tests for the shared-VRAM F3 diagnostic batch planner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import f3_vram_batch_planner_v1 as planner


SHA_A = "a" * 64
SHA_B = "b" * 64
ROOT = "/workspace/lagrangian-fluid-lab"


def _gpu(index: int, free: int) -> planner.GpuSnapshot:
    return planner.GpuSnapshot(index, 49140 - free, free, 49140, 0)


def _job(job_id: str, *, model: str = "graph_raw", seed: int = 29, case: str = "F3_DEV_00") -> dict:
    prefix = f"/tmp/{job_id}"
    return {
        "job_id": job_id,
        "model": model,
        "seed": seed,
        "case_id": case,
        "manifest_path": f"{ROOT}/campaigns/core-v1/f3-dataset-v2.json",
        "manifest_sha256": SHA_A,
        "checkpoint_path": f"/tmp/{model}-seed{seed}.pt",
        "checkpoint_sha256": SHA_B,
        "cwd": ROOT,
        "argv": [".venv/bin/python", "scripts/core_learning.py", "evaluate",
                 "--maximum-steps", "835", "--diagnostic"],
        "output_paths": [f"{prefix}-evaluation.json", f"{prefix}-trajectory.h5"],
        "estimated_vram_mib": 4096,
        "cpu_slots": 4,
    }


def test_parse_nvidia_smi_csv_accepts_shared_gpu_snapshot():
    snapshots = planner.parse_nvidia_smi_csv(
        "0, 12143, 36368, 49140, 0\n1, 19822, 28690, 49140, 10\n"
    )
    assert snapshots[0].index == 0
    assert snapshots[1].memory_free_mib == 28690


def test_plan_uses_occupied_but_memory_sufficient_gpus():
    plan = planner.plan_jobs(
        [_job("job-a"), _job("job-b", case="F3_DEV_01")],
        [_gpu(0, 12000), _gpu(1, 20000)],
        min_free_mib=8000,
    )
    assignments = {job["job_id"]: job["gpu_index"] for job in plan["jobs"]}
    assert assignments == {"job-a": 1, "job-b": 1}
    assert plan["planner_policy"]["gpu_is_shareable"] is True
    assert plan["summary"]["planned_count"] == 2


def test_plan_fails_closed_when_headroom_is_insufficient():
    plan = planner.plan_jobs([_job("job-a")], [_gpu(0, 12000)], min_free_mib=9000)
    assert plan["jobs"][0]["status"] == "blocked_resource_headroom"
    assert plan["summary"]["blocked_count"] == 1


def test_planner_reserves_vram_across_shared_jobs():
    plan = planner.plan_jobs(
        [_job("job-a"), _job("job-b", case="F3_DEV_01"), _job("job-c", case="F3_DEV_02")],
        [_gpu(0, 18000), _gpu(1, 9000)],
        min_free_mib=8000,
    )
    statuses = {job["job_id"]: job["status"] for job in plan["jobs"]}
    assert statuses == {"job-a": "planned", "job-b": "planned", "job-c": "blocked_resource_headroom"}
    assert plan["summary"]["reserved_vram_mib_by_gpu"] == {"0": 8192, "1": 0}


def test_duplicate_output_or_model_seed_case_is_rejected():
    first = _job("job-a")
    duplicate = _job("job-b")
    with pytest.raises(planner.PlannerError, match="model/seed/case"):
        planner.plan_jobs([first, duplicate], [_gpu(0, 20000)])
    duplicate_case = _job("job-c", case="F3_DEV_01")
    duplicate_case["output_paths"][0] = first["output_paths"][0]
    with pytest.raises(planner.PlannerError, match="output_paths"):
        planner.plan_jobs([first, duplicate_case], [_gpu(0, 20000)])


def test_diagnostic_contract_and_canonical_output(tmp_path: Path):
    path = tmp_path / "plan.json"
    plan = planner.plan_jobs([_job("job-a")], [_gpu(0, 20000)])
    assert plan["diagnostic_only"] is True
    assert plan["formal"] is False
    assert plan["qualification_credit"] == 0
    path.write_text(planner.canonical_json(plan) + "\n", encoding="utf-8")
    parsed = json.loads(path.read_text(encoding="utf-8"))
    assert path.read_text(encoding="utf-8")[:-1] == planner.canonical_json(parsed)


@pytest.mark.parametrize("mutation", ["no_diagnostic", "relative_cwd", "traversal_output"])
def test_unsafe_launch_contract_is_rejected(mutation):
    job = _job("job-a")
    if mutation == "no_diagnostic":
        job["argv"] = job["argv"][:-1]
    elif mutation == "relative_cwd":
        job["cwd"] = "."
    else:
        job["output_paths"][0] = "/tmp/../unsafe.json"
    with pytest.raises(planner.PlannerError, match="fail-closed"):
        planner.plan_jobs([job], [_gpu(0, 20000)])


def test_query_nvidia_smi_uses_fixed_command():
    calls = []

    class Result:
        stdout = "0, 1, 2, 3, 4\n"

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return Result()

    snapshots = planner.query_nvidia_smi(runner=runner)
    assert snapshots[0].memory_free_mib == 2
    assert calls[0][0][0] == "nvidia-smi"
    assert "--format=csv,noheader,nounits" in calls[0][0]
