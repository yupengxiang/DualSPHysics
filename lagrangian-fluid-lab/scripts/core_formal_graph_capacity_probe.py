#!/usr/bin/env python3
"""Probe representative full-field graph optimizer capacity after data gating.

This bounded diagnostic reads one F4 compact-reader transition, builds the
complete particle-axis neighbor table, and executes a few ``graph_raw`` Adam
updates on the declared device.  It estimates, but does not claim, the cost of
32000 updates.  The output is a resource probe, never a Core training receipt:
no checkpoint, registry, ledger, job, or formal denominator is touched.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import resource
from pathlib import Path
import sys
import time
from typing import Any, Mapping, Sequence

import numpy as np
import torch

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.core_dataset import CoreDataset
from scripts.core_learning import _known_inputs_for_learning, tensors
from scripts.core_models import DualIncrementModel
from scripts.core_strict_json import (
    absolute_path_without_following_leaf,
    read_bounded_raw_json,
    strict_json_object,
)


SCHEMA = "core.formal_graph_capacity_probe.v1"
TARGET_UPDATES = 32000
MAX_PROBE_UPDATES = 8


def _load_candidate(path: str | Path) -> Mapping[str, Any]:
    resolved = absolute_path_without_following_leaf(path)
    raw = read_bounded_raw_json(resolved, label="graph probe candidate")
    payload = strict_json_object(raw, label="graph probe candidate")
    if payload.get("schema") != "core.formal_release_candidate.v1":
        raise ValueError("graph probe requires a formal release candidate record")
    if payload.get("data_contract_ready") is not True:
        raise ValueError("schema/data gate is not ready; graph probe was not started")
    if payload.get("formal_release") is not False or payload.get("formal_job_count") != 0:
        raise ValueError("graph probe cannot run as formal training")
    admission = payload.get("admission_observation")
    if not isinstance(admission, Mapping):
        raise ValueError("graph probe requires an explicit admission observation")
    denominator = admission.get("production_denominator")
    if not isinstance(denominator, Mapping):
        raise ValueError("graph probe requires an explicit production denominator")
    counts = {
        name: denominator.get(name)
        for name in (
            "included_case_count",
            "hard_integrity_pass_bound_count",
            "structural_pass_bound_count",
        )
    }
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 1
           for value in counts.values()):
        raise ValueError("graph probe requires positive integer production denominator counts")
    if counts["hard_integrity_pass_bound_count"] != counts["included_case_count"]:
        raise ValueError("graph probe requires complete hard-audit denominator")
    if counts["structural_pass_bound_count"] != counts["included_case_count"]:
        raise ValueError("graph probe requires complete structural-audit denominator")
    return payload


def _manifest_binding(candidate: Mapping[str, Any], manifest: Path, root: Path
                      ) -> tuple[dict[str, Any], dict[str, Any]]:
    raw = read_bounded_raw_json(manifest, label="graph probe reader manifest")
    payload = strict_json_object(raw, label="graph probe reader manifest")
    observed = hashlib.sha256(raw).hexdigest()
    for binding in candidate.get("manifest_bindings", []):
        if binding.get("path") == manifest.resolve().relative_to(root.resolve()).as_posix():
            if binding.get("sha256") != observed:
                raise ValueError("graph probe manifest hash differs from candidate binding")
            return payload, {"path": binding["path"], "sha256": observed}
    raise ValueError("graph probe manifest is not bound by the candidate")


def run_probe(candidate: Mapping[str, Any], *, manifest: str | Path,
              data_root: str | Path, updates: int = 4, hidden: int = 64,
              centers: int = 256, seed: int = 17, device: str = "cuda") -> dict[str, Any]:
    if not 1 <= int(updates) <= MAX_PROBE_UPDATES:
        raise ValueError(f"bounded graph probe accepts 1..{MAX_PROBE_UPDATES} updates")
    if int(hidden) < 1 or int(centers) < 1:
        raise ValueError("hidden and centers must be positive")
    root = Path(data_root).expanduser().resolve()
    manifest_path = absolute_path_without_following_leaf(manifest)
    manifest_payload, binding = _manifest_binding(candidate, manifest_path, root)
    if torch.device(device).type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested for full-field graph probe but unavailable")
    resolved_device = torch.device(device)
    torch.manual_seed(int(seed))
    read_started = time.perf_counter()
    with CoreDataset(manifest_payload, root) as dataset:
        train_cases = dataset.case_ids("train")
        if not train_cases:
            raise ValueError("bound F4 compact manifest has no train cases")
        case_id = train_cases[0]
        if dataset.record(case_id).get("family") != "F4":
            raise ValueError("full-field graph probe requires an F4 train case")
        state, known, dt, target = dataset.training_transition(case_id, 0)
        known = _known_inputs_for_learning(known)
        read_seconds = time.perf_counter() - read_started
        tensor_started = time.perf_counter()
        args, _, tensor_diagnostics = tensors(state, known, dt, resolved_device)
        target_tensor = torch.as_tensor(
            np.column_stack((target.displacement, target.delta_velocity)),
            dtype=torch.float32, device=resolved_device)
        center_count = min(int(centers), state.count)
        center_indices = torch.arange(center_count, dtype=torch.long, device=resolved_device)
        tensor_seconds = time.perf_counter() - tensor_started

        model = DualIncrementModel("graph_raw", hidden=int(hidden)).to(resolved_device)
        optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
        if resolved_device.type == "cuda":
            torch.cuda.reset_peak_memory_stats(resolved_device)
            torch.cuda.synchronize(resolved_device)
        update_times: list[float] = []
        losses: list[float] = []
        for _ in range(int(updates)):
            started = time.perf_counter()
            optimizer.zero_grad(set_to_none=True)
            prediction = model(*args, centers=center_indices)
            loss = torch.mean((prediction - target_tensor[center_indices]) ** 2)
            loss.backward()
            optimizer.step()
            if resolved_device.type == "cuda":
                torch.cuda.synchronize(resolved_device)
            update_times.append(time.perf_counter() - started)
            losses.append(float(loss.detach().cpu()))
        if resolved_device.type == "cuda":
            peak_gpu = int(torch.cuda.max_memory_allocated(resolved_device))
            gpu_name = torch.cuda.get_device_name(resolved_device)
        else:
            peak_gpu = 0
            gpu_name = None

        observed_hdf5 = dataset.record(case_id)
        mean_update = float(np.mean(update_times))
        median_update = float(np.median(update_times))
        per_update_full_pipeline = read_seconds + tensor_seconds + median_update
        usage = resource.getrusage(resource.RUSAGE_SELF)
        return {
            "schema": SCHEMA,
            "mode": "bounded_full_field_graph_raw_capacity_probe",
            "status": "completed",
            "diagnostic_only": True,
            "formal_release": False,
            "formal_training": False,
            "formal_job_count": 0,
            "required_formal_job_count": 9,
            "candidate_record_id": candidate.get("record_id"),
            "candidate_data_contract_ready": True,
            "manifest_binding": binding,
            "case": {
                "case_id": case_id,
                "family": "F4",
                "split": observed_hdf5.get("split"),
                "particles": int(state.count),
                "frame": 0,
                "trajectory_path": observed_hdf5.get("hdf5"),
                "trajectory_sha256": observed_hdf5.get("sha256"),
                "trajectory_bytes": observed_hdf5.get("bytes"),
            },
            "protocol": {
                "model_kind": "graph_raw",
                "seed": int(seed),
                "hidden": int(hidden),
                "centers_per_update": int(center_count),
                "probe_updates": int(updates),
                "target_updates": TARGET_UPDATES,
                "optimizer": "Adam",
                "learning_rate": 1e-3,
                "device": str(resolved_device),
                "gpu_name": gpu_name,
                "full_particle_axis": True,
            },
            "io_and_graph": {
                "read_transition_seconds": read_seconds,
                "tensor_and_neighbor_build_seconds": tensor_seconds,
                "neighbor_diagnostics": tensor_diagnostics,
                "hdf5_opened_for_diagnostic": True,
            },
            "updates": {
                "completed": int(updates),
                "update_seconds": update_times,
                "mean_update_seconds": mean_update,
                "median_update_seconds": median_update,
                "loss_mse": losses,
                "estimated_32000_update_seconds_median": median_update * TARGET_UPDATES,
                "estimated_32000_update_seconds_plus_one_io": (
                    read_seconds + tensor_seconds + median_update * TARGET_UPDATES
                ),
                "estimated_32000_full_pipeline_seconds": per_update_full_pipeline * TARGET_UPDATES,
                "estimated_32000_full_pipeline_hours": per_update_full_pipeline * TARGET_UPDATES / 3600.0,
                "full_pipeline_basis": "one representative HDF5 transition plus neighbor rebuild per optimizer update",
                "estimate_is_extrapolation": True,
            },
            "resource": {
                "peak_gpu_memory_bytes": peak_gpu,
                "peak_gpu_memory_mib": peak_gpu / (1024.0 * 1024.0),
                "peak_rss_mib": usage.ru_maxrss / 1024.0,
                "user_cpu_seconds": usage.ru_utime,
                "system_cpu_seconds": usage.ru_stime,
            },
            "execution_constraints": {
                "trajectory_files_opened": True,
                "future_state_inputs": False,
                "formal_runs_started": 0,
                "gpu_started": resolved_device.type == "cuda",
                "solver_started": False,
                "submitted": False,
                "central_registry_mutation": 0,
                "central_ledger_mutation": 0,
                "checkpoint_written": False,
                "training_receipt_written": False,
            },
            "interpretation": (
                "This is a bounded full-field graph_raw probe on the local declared device. "
                "The 32000-update estimate assumes stationary per-update cost and excludes "
                "checkpoint/validation overhead; it is diagnostic capacity evidence, not a formal run."
            ),
        }


def write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"graph probe output is immutable and already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".partial")
    partial.write_text(json.dumps(payload, indent=2, sort_keys=True,
                                  ensure_ascii=False, allow_nan=False) + "\n",
                       encoding="utf-8")
    partial.replace(target)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--updates", type=int, default=4)
    parser.add_argument("--hidden", type=int, default=64)
    parser.add_argument("--centers", type=int, default=256)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--device", default="cuda")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    candidate = _load_candidate(args.candidate)
    result = run_probe(
        candidate, manifest=args.manifest, data_root=args.data_root,
        updates=args.updates, hidden=args.hidden, centers=args.centers,
        seed=args.seed, device=args.device)
    write_json(args.output, result)
    print(json.dumps({
        "schema": result["schema"],
        "status": result["status"],
        "diagnostic_only": result["diagnostic_only"],
        "formal_job_count": result["formal_job_count"],
        "particles": result["case"]["particles"],
        "probe_updates": result["protocol"]["probe_updates"],
        "estimated_32000_update_seconds_median": result["updates"]["estimated_32000_update_seconds_median"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
