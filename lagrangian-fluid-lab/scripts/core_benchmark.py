#!/usr/bin/env python3
"""Portable Core entrypoint: inspect/verify reader data and optionally reproduce a registered model."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import resource
import sys
import tempfile
import time

# Executable both by absolute script path and python -m scripts.core_benchmark.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.core_contract import updater_oracle
from scripts.core_dataset import import_f3_manifest
from scripts.core_cfd_dataset import open_dataset
from scripts.core_runtime import atomic_json, digest


MODEL_CODE_FILES = (
    "core_benchmark.py", "core_runtime.py", "core_contract.py", "core_dataset.py",
    "core_models.py", "core_learning.py", "core_cfd_dataset.py", "core_evaluation.py",
    "core_physics.py", "core_reproduction_check.py",
)
CHECKPOINT_REGISTRY_SCHEMA = "core.bundled_checkpoints.v1"
MODEL_REPRODUCTION_SCHEMA = "core.model_reproduction.v1"
MODEL_SCORE_SCHEMA = "core.model_reproduction.score.v1"
PHASE_PLAN_SCHEMA = "core.phase_plan.v1"
PHASE_NAMES = ("verify", "inspect", "train", "rollout", "evaluate", "reproduce")


def _canonical_hash(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def _sha256_hex(value, *, name):
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{name} must be a 64-character SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as error:
        raise ValueError(f"{name} must be a 64-character SHA-256 hex digest") from error
    return value.lower()


def _environment_evidence():
    packages = {}
    for name in ("numpy", "scipy", "h5py", "torch"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {
        "python": sys.version,
        "python_executable": str(Path(sys.executable).resolve()),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "packages": packages,
    }


def _resource_evidence(device=None):
    usage = resource.getrusage(resource.RUSAGE_SELF)
    result = {
        "peak_rss_mib": float(usage.ru_maxrss / 1024),
        "user_cpu_seconds": float(usage.ru_utime),
        "system_cpu_seconds": float(usage.ru_stime),
    }
    if device is not None:
        result["device"] = str(device)
    try:
        import torch
        if torch.cuda.is_available():
            result["peak_gpu_memory_bytes"] = int(torch.cuda.max_memory_allocated())
        else:
            result["peak_gpu_memory_bytes"] = 0
    except (ImportError, RuntimeError):
        result["peak_gpu_memory_bytes"] = 0
    return result


def _code_evidence():
    root = Path(__file__).resolve().parent
    files = []
    for name in MODEL_CODE_FILES:
        path = root / name
        if not path.is_file():
            raise ValueError(f"model reproduction code dependency is missing: {name}")
        files.append({"path": f"scripts/{name}", "sha256": digest(path),
                      "bytes": path.stat().st_size})
    return {"files": files, "closure_sha256": _canonical_hash(
        [{"path": item["path"], "sha256": item["sha256"]} for item in files])}


def _portable_path(root, value, *, name):
    path = Path(value)
    root = Path(root).resolve()
    if path.is_absolute():
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(root)
        except ValueError as error:
            raise ValueError(f"{name} must be inside data root") from error
    else:
        if ".." in path.parts:
            raise ValueError(f"{name} must be a portable relative path")
        relative = path
        resolved = (root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{name} escapes data root") from error
    return relative.as_posix(), resolved


def _manifest_path(manifest, data_root):
    """Resolve a manifest using the explicit data_root path contract.

    The benchmark entrypoint is often called from a worker directory that is
    unrelated to the bundle.  A relative manifest therefore means
    ``data_root/<manifest>`` everywhere in this module; resolving it once
    prevents inspect, verify, rollout/evaluate setup, and reproduction from
    silently using different cwd-dependent files.
    """
    if not isinstance(manifest, (str, Path)):
        return manifest
    path = Path(manifest).expanduser()
    if not path.is_absolute():
        path = Path(data_root).expanduser() / path
    return path.resolve()


def phase_plan(manifest, data_root, *, case_ids=None):
    """Audit the six Core phases and freeze their registered denominators.

    This is a read-only metadata/temporal-axis audit.  It opens the registered
    reader only to obtain case identity and saved times; no state prediction,
    optimizer, GPU, registry, or ledger action is performed.  The resulting
    denominator is intentionally explicit so later rollout/evaluation reports
    cannot drop a case or shrink its missing-frame penalty.
    """
    root = Path(data_root).expanduser().resolve()
    manifest_path = _manifest_path(manifest, root)
    if not isinstance(manifest_path, (str, Path)):
        raise ValueError("phase plan requires a JSON manifest path")
    manifest_path = Path(manifest_path)
    with open_dataset(manifest_path, root) as data:
        registered = tuple(data.case_ids())
        selected = tuple(registered if case_ids is None else case_ids)
        if len(set(selected)) != len(selected):
            raise ValueError("phase plan case selection contains duplicates")
        unknown = sorted(set(selected) - set(registered))
        if unknown:
            raise ValueError("phase plan case is not registered: " + ", ".join(unknown))
        denominators = {}
        missing = []
        for case_id in selected:
            times = data.times(case_id)
            expected_frames = len(times) - 1
            if expected_frames < 1:
                missing.append(case_id)
                denominators[case_id] = {
                    "expected_frames": None,
                    "trajectory_frames": None,
                    "status": "missing_registered_future_frames",
                }
                continue
            record = data.record(case_id)
            denominators[case_id] = {
                "expected_frames": int(expected_frames),
                "trajectory_frames": int(expected_frames + 1),
                "family": str(record["family"]),
                "split": str(record["split"]),
                "status": "registered",
            }

    phases = []
    entrypoints = {
        "verify": "core_benchmark.py verify",
        "inspect": "core_benchmark.py inspect",
        "train": "core_benchmark.py train -> core_learning.py train",
        "rollout": "core_benchmark.py rollout -> core_learning.py rollout",
        "evaluate": "core_benchmark.py evaluate -> core_learning.py evaluate",
        "reproduce": "core_benchmark.py reproduce",
    }
    for order, name in enumerate(PHASE_NAMES, start=1):
        phases.append({
            "order": order,
            "name": name,
            "entrypoint": entrypoints[name],
            "required": True,
            "read_only": name != "train",
            "training_started": False,
            "gpu_started": False,
            "future_state_inputs": False,
            "denominator_source": "registered time axis; expected_frames=len(time)-1",
        })
    passed = bool(selected) and not missing
    return {
        "schema": PHASE_PLAN_SCHEMA,
        "passed": passed,
        "manifest": {"path": str(manifest_path), "sha256": digest(manifest_path)},
        "data_root": str(root),
        "phases": phases,
        "phase_order": list(PHASE_NAMES),
        "denominator": {
            "case_ids": list(selected),
            "registered_case_count": len(selected),
            "expected_frames_by_case": {
                case_id: row["expected_frames"] for case_id, row in denominators.items()
            },
            "trajectory_frames_by_case": {
                case_id: row["trajectory_frames"] for case_id, row in denominators.items()
            },
            "cases": denominators,
            "missing_denominator_case_ids": list(missing),
            "missing_execution_preserves_expected_frames": True,
            "policy": "fixed registered future-frame denominator; never shrink on failure",
        },
        "guards": {
            "trajectory_files_opened": True,
            "trajectory_state_frames_read": 0,
            "predictor_future_state_inputs": False,
            "future_state_inputs": False,
            "registry_written": False,
            "ledger_written": False,
            "formal_training_started": False,
        },
        "formal_readiness": {
            "status": "blocked",
            "formal_admission": False,
            "formal_training": False,
            "formal_job_count": 0,
            "required_formal_job_count": 9,
            "diagnostic_runs_counted_as_formal": False,
        },
    }


def _checkpoint_registration(root, checkpoint):
    """Resolve a checkpoint only through the immutable bundle registry."""
    registry_path = Path(root).resolve() / "checkpoints.json"
    if not registry_path.is_file():
        raise ValueError("checkpoint-backed reproduction requires checkpoints.json")
    try:
        registry = json.loads(registry_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("invalid checkpoints.json") from error
    if registry.get("schema") != CHECKPOINT_REGISTRY_SCHEMA:
        raise ValueError("unsupported checkpoint registry version")
    rows = registry.get("checkpoints")
    if not isinstance(rows, list) or not rows:
        raise ValueError("checkpoint registry must contain at least one checkpoint")
    requested = checkpoint.get("path") if isinstance(checkpoint, dict) else checkpoint
    relative, path = _portable_path(root, requested, name="checkpoint")
    matches = [row for row in rows if isinstance(row, dict) and row.get("path") == relative]
    if len(matches) != 1:
        raise ValueError("checkpoint is not registered exactly once")
    row = dict(matches[0])
    registered_hash = _sha256_hex(row.get("sha256"), name="checkpoint sha256")
    if not path.is_file() or digest(path) != registered_hash:
        raise ValueError("checkpoint artifact hash mismatch")
    supplied_hash = checkpoint.get("sha256") if isinstance(checkpoint, dict) else None
    if supplied_hash is not None and _sha256_hex(supplied_hash, name="checkpoint sha256") != registered_hash:
        raise ValueError("checkpoint supplied hash mismatch")
    for key in ("model_kind", "seed", "update"):
        if key not in row:
            raise ValueError(f"checkpoint registry entry missing {key}")
    row["path"] = relative
    row["sha256"] = registered_hash
    row["registry_path"] = str(registry_path)
    row["registry_sha256"] = digest(registry_path)
    return path, row


def _safe_case_stem(case_id, index):
    raw = str(case_id)
    safe = "".join(character if character.isalnum() or character in "._-" else "_"
                   for character in raw).strip("._") or f"case-{index:03d}"
    if safe != raw:
        safe += "-" + hashlib.sha256(raw.encode()).hexdigest()[:10]
    return f"{index:03d}-{safe}"


def _report_artifact_path(report, report_path, reference):
    if isinstance(reference, dict):
        value = reference.get("path")
    else:
        value = reference
    if not isinstance(value, (str, Path)):
        raise ValueError("paired artifact path is missing")
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    root = report.get("artifact_root")
    if root is None:
        root = Path(report_path).resolve().parent
    root = Path(root)
    if not root.is_absolute():
        root = (Path(report_path).resolve().parent / root).resolve()
    candidate = (root / path).resolve()
    # Reports are often collected from another host together with their
    # relative artifacts.  An absolute artifact_root from that host is useful
    # provenance but may no longer exist after collection; resolve the same
    # registered relative path beside the collected report in that case.
    if not candidate.exists() and not Path(value).is_absolute():
        fallback = (Path(report_path).resolve().parent / path).resolve()
        if fallback.exists():
            return fallback
    return candidate


def _verified_report_artifact(report, report_path, reference, *, label):
    path = _report_artifact_path(report, report_path, reference)
    if not path.is_file():
        raise ValueError(f"{label} artifact is missing")
    if not isinstance(reference, dict):
        raise ValueError(f"{label} artifact registration is missing")
    expected_hash = _sha256_hex(reference.get("sha256"), name=f"{label} sha256")
    if digest(path) != expected_hash:
        raise ValueError(f"{label} artifact hash mismatch")
    expected_bytes = reference.get("bytes")
    if isinstance(expected_bytes, bool) or not isinstance(expected_bytes, int) or expected_bytes < 0:
        raise ValueError(f"{label} artifact byte count is malformed")
    if path.stat().st_size != expected_bytes:
        raise ValueError(f"{label} artifact byte count mismatch")
    return path


def _paired_case_trajectory(row):
    if not isinstance(row, dict):
        raise ValueError("paired case row is malformed")
    trajectory = row.get("trajectory")
    if isinstance(trajectory, dict) and trajectory.get("path") is not None:
        return trajectory
    if row.get("trajectory_output") is not None:
        return {"path": row["trajectory_output"]}
    raise ValueError("paired case trajectory is missing")


def inspect_dataset(manifest, data_root):
    manifest_path = _manifest_path(manifest, data_root)
    with open_dataset(manifest_path, data_root) as data:
        cases = []
        for case in data.case_ids():
            state = data.read_state(case, 0)
            times = data.times(case)
            record = data.record(case)
            cases.append({"case_id": case, "family": record["family"], "split": record["split"],
                          "particles": state.count, "frames": len(times), "time_start_s": float(times[0]),
                          "time_end_s": float(times[-1]), "velocity_semantics": "native saved numerical velocity"})
        return {"schema": "core.inspection.v1", "manifest_sha256": digest(manifest_path), "case_count": len(cases),
                "families": dict(Counter(c["family"] for c in cases)),
                "splits": dict(Counter(c["split"] for c in cases)), "cases": cases,
                "scientific_status": "source_claims_only; inspection does not qualify data"}


def verify_dataset(manifest, data_root, *, case_ids=None, full_scan=False):
    started = time.monotonic()
    records = []
    manifest_path = _manifest_path(manifest, data_root)
    with open_dataset(manifest_path, data_root) as data:
        cases = case_ids or data.case_ids()
        for case in cases:
            hashes = data.verify_sources([case])
            # File integrity alone cannot validate the reconstructed public
            # inputs: also check their semantic contract hash.
            data.known_inputs(case)
            n = len(data.times(case))
            indices = range(n - 1) if full_scan else sorted({0, (n - 1) // 2, n - 2})
            oracles = [data.oracle(case, i) for i in indices]
            passed = all(o["position_max_abs_error"] < 1e-10 and o["native_velocity_max_abs_error"] < 1e-10 for o in oracles)
            records.append({"case_id": case, "sha256": hashes[case], "full_particle_axis": True,
                            "transition_count": len(oracles), "passed": passed, "oracles": oracles})
    return {"schema": "core.verification.v1", "passed": all(c["passed"] for c in records),
            "full_temporal_scan": full_scan, "case_count": len(records), "cases": records,
            "wall_seconds": time.monotonic() - started, "host": platform.node(),
            "manifest_sha256": digest(manifest_path), "qualification_inferred": False}


def _load_json(path, *, description):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid {description}") from error


def _compare_paired_reproduction(current, current_report_path, paired_report_path):
    """Compare local artifacts with a separately materialized host report."""
    from scripts import core_reproduction_check

    paired_report_path = Path(paired_report_path).resolve()
    paired = _load_json(paired_report_path, description="paired reproduction report")
    errors = []
    if paired.get("schema") != MODEL_REPRODUCTION_SCHEMA:
        errors.append("paired report is not checkpoint-backed model reproduction")
    paired_host = paired.get("reproduction_host")
    current_host = current.get("reproduction_host")
    if not isinstance(current_host, str) or not current_host:
        errors.append("local reproduction host evidence is missing")
    if not isinstance(paired_host, str) or not paired_host:
        errors.append("paired reproduction host evidence is missing")
    elif paired_host == current_host:
        errors.append("paired artifacts do not provide distinct host evidence")
    for label, report in (("local", current), ("paired", paired)):
        evidence = report.get("verification") if isinstance(report, dict) else None
        observed = evidence.get("host") if isinstance(evidence, dict) else None
        expected = report.get("reproduction_host") if isinstance(report, dict) else None
        if not isinstance(observed, str) or not observed:
            errors.append(f"{label} host verification evidence is missing")
        elif observed != expected:
            errors.append(f"{label} host verification evidence mismatch")
    for key in ("dataset_id", "manifest_sha256", "checkpoint_sha256", "bundle_sha256", "model_kind", "seed", "hidden"):
        if (key in current or key in paired) and current.get(key) != paired.get(key):
            errors.append(f"paired identity mismatch:{key}")
    current_code = current.get("code", {}).get("closure_sha256") if isinstance(current.get("code"), dict) else None
    paired_code = paired.get("code", {}).get("closure_sha256") if isinstance(paired.get("code"), dict) else None
    if not isinstance(current_code, str) or not isinstance(paired_code, str) or current_code != paired_code:
        errors.append("paired identity mismatch:code_closure_sha256")
    current_cases = current.get("cases")
    paired_cases = paired.get("cases")
    if not isinstance(current_cases, dict) or not isinstance(paired_cases, dict):
        errors.append("paired case registry is missing")
        current_cases = current_cases if isinstance(current_cases, dict) else {}
        paired_cases = paired_cases if isinstance(paired_cases, dict) else {}
    if set(current_cases) != set(paired_cases):
        errors.append("paired case registry mismatch")

    current_score_ref = current.get("score_artifact")
    paired_score_ref = paired.get("score_artifact")
    score_comparison = None
    try:
        current_score_path = _verified_report_artifact(
            current, current_report_path, current_score_ref, label="local score")
        paired_score_path = _verified_report_artifact(
            paired, paired_report_path, paired_score_ref, label="paired score")
        current_score = _load_json(current_score_path, description="local score receipt")
        paired_score = _load_json(paired_score_path, description="paired score receipt")
        if (current_score.get("schema") != MODEL_SCORE_SCHEMA
                or paired_score.get("schema") != MODEL_SCORE_SCHEMA):
            raise ValueError("paired score receipt schema mismatch")
        expected_by_case = {
            case_id: int(current_cases[case_id]["rollout"]["expected_frames"])
            for case_id in current_cases if isinstance(current_cases.get(case_id), dict)
        }
        if expected_by_case and len(set(expected_by_case.values())) == 1:
            score_comparison = core_reproduction_check.compare_scores(
                current_score_path, paired_score_path,
                expected_frames=next(iter(expected_by_case.values())),
            )
        else:
            # The registered comparator accepts one denominator per call. Keep
            # its validation and tolerances for heterogeneous horizons by
            # comparing one case-specific receipt at a time.
            score_cases = {}
            for case_id, expected in sorted(expected_by_case.items()):
                if case_id not in paired_score.get("cases", {}):
                    errors.append("paired score case mismatch:" + case_id)
                    continue
                with tempfile.TemporaryDirectory(prefix="core-score-compare-") as directory:
                    left = Path(directory) / "left.json"
                    right = Path(directory) / "right.json"
                    left_payload = dict(current_score)
                    right_payload = dict(paired_score)
                    left_payload["cases"] = {case_id: current_score.get("cases", {}).get(case_id)}
                    right_payload["cases"] = {case_id: paired_score.get("cases", {}).get(case_id)}
                    left.write_text(json.dumps(left_payload))
                    right.write_text(json.dumps(right_payload))
                    score_cases[case_id] = core_reproduction_check.compare_scores(
                        left, right, expected_frames=expected)
            score_comparison = {
                "passed": bool(score_cases) and all(row["passed"] for row in score_cases.values()),
                "cases": score_cases,
                "errors": [error for row in score_cases.values() for error in row.get("errors", [])],
                "mode": "per_case_registered_denominators",
            }
    except (OSError, TypeError, ValueError, KeyError) as error:
        errors.append(f"score comparison error:{type(error).__name__}:{error}")

    trajectory_comparison = {}
    for case_id in sorted(set(current_cases) & set(paired_cases)):
        try:
            current_row = current_cases[case_id]
            paired_row = paired_cases[case_id]
            current_ref = _paired_case_trajectory(current_row)
            paired_ref = _paired_case_trajectory(paired_row)
            current_path = _verified_report_artifact(
                current, current_report_path, current_ref, label=f"local trajectory:{case_id}")
            paired_path = _verified_report_artifact(
                paired, paired_report_path, paired_ref, label=f"paired trajectory:{case_id}")
            expected = int(current_row["rollout"]["expected_frames"]) + 1
            trajectory_comparison[case_id] = core_reproduction_check.compare(
                current_path, paired_path, expected_frames=expected)
        except (OSError, TypeError, ValueError, KeyError) as error:
            trajectory_comparison[case_id] = {
                "passed": False,
                "errors": [f"trajectory comparison error:{type(error).__name__}:{error}"],
            }
    if score_comparison is not None and not score_comparison.get("passed", False):
        errors.append("paired score comparison failed")
    if any(not row.get("passed", False) for row in trajectory_comparison.values()):
        errors.append("paired trajectory comparison failed")
    if paired.get("passed") is not True:
        errors.append("paired local reproduction did not pass")
    if paired.get("full_horizon_reproduction") is not True:
        errors.append("paired report is not a complete full-horizon reproduction")
    return {
        "schema": "core.model_reproduction.comparison.v1",
        "status": "compared",
        "passed": not errors,
        "errors": errors,
        "observed_hosts": sorted({host for host in (current_host, paired_host) if isinstance(host, str)}),
        "distinct_host_evidence": len({host for host in (current_host, paired_host) if isinstance(host, str)}) == 2,
        "paired_report": str(paired_report_path),
        "score": score_comparison,
        "trajectory": trajectory_comparison,
    }


def _reproduce_checkpoint(manifest, data_root, case_ids, source_host, *, checkpoint,
                          output_dir, device="cpu", paired_report=None, report_path=None):
    from scripts.core_evaluation import aggregate_cases, score_case
    from scripts.core_learning import (_build_predictor_from_checkpoint,
                                       _characteristic_scales, rollout_case)
    from scripts.core_package import verify_bundle

    if not case_ids:
        raise ValueError("checkpoint-backed reproduction requires explicit --case-id selection")
    if output_dir is None:
        raise ValueError("checkpoint-backed reproduction requires --output-dir")
    root = Path(data_root).resolve()
    output_root = Path(output_dir).resolve()
    report_path = Path(report_path).resolve() if report_path is not None else output_root / "reproduction.json"
    try:
        output_root.relative_to(root)
    except ValueError:
        pass
    else:
        raise ValueError("reproduction output must be outside the immutable bundle/data root")
    try:
        report_path.relative_to(root)
    except ValueError:
        pass
    else:
        raise ValueError("reproduction report must be outside the immutable bundle/data root")
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_path = _manifest_path(manifest, root)
    try:
        manifest_path.relative_to(root)
    except ValueError as error:
        raise ValueError("portable reproduction manifest must be inside data root") from error
    if not manifest_path.is_file():
        raise ValueError("reproduction manifest is missing")
    if manifest_path != (root / "dataset.json").resolve():
        raise ValueError("reproduction must use the bundle registered dataset.json")
    bundle_path = root / "bundle.json"
    if not bundle_path.is_file():
        raise ValueError("checkpoint-backed reproduction requires an immutable bundle.json")
    bundle_verification = verify_bundle(root)
    selected = tuple(case_ids)
    if len(set(selected)) != len(selected):
        raise ValueError("reproduction case selection contains duplicates")
    with open_dataset(manifest_path, root) as data:
        registered = set(data.case_ids())
    unknown = sorted(set(selected) - registered)
    if unknown:
        raise ValueError("reproduction case is not registered: " + ", ".join(unknown))
    source_verification = verify_dataset(manifest_path, root, case_ids=list(selected), full_scan=True)
    checkpoint_path, checkpoint_row = _checkpoint_registration(root, checkpoint)
    predictor, payload = _build_predictor_from_checkpoint(checkpoint_path, device=device,
                                                          chunk_size=256)
    for key in ("model_kind", "seed", "update"):
        if payload.get(key) != checkpoint_row.get(key):
            raise ValueError(f"checkpoint payload disagrees with registry: {key}")
    if str(device).startswith("cuda"):
        try:
            import torch
            if not torch.cuda.is_available():
                raise RuntimeError("CUDA requested but unavailable")
            torch.cuda.reset_peak_memory_stats(torch.device(device))
        except ImportError as error:
            raise RuntimeError("CUDA checkpoint reproduction requires torch") from error

    started = time.monotonic()
    case_rows = {}
    score_rows = {}
    registry = {}
    cases_root = output_root / "cases"
    dataset_manifest_sha256 = None
    with open_dataset(manifest_path, root) as data:
        dataset_manifest_sha256 = getattr(data, "manifest_sha256", None)
        saved_manifest_sha256 = (payload.get("config", {}).get("manifest_sha256")
                                if isinstance(payload.get("config"), dict) else None)
        if not isinstance(saved_manifest_sha256, str) or len(saved_manifest_sha256) != 64:
            raise ValueError("checkpoint lacks dataset manifest hash")
        if (dataset_manifest_sha256 is not None
                and saved_manifest_sha256 != dataset_manifest_sha256):
            raise ValueError("checkpoint dataset manifest hash mismatch")
        for index, case_id in enumerate(selected):
            # The dataset object is the authoritative registered case view;
            # this loop intentionally does not infer cases from HDF5 filenames.
            case_stem = _safe_case_stem(case_id, index)
            trajectory_path = cases_root / case_stem / "trajectory.h5"
            progress_path = cases_root / case_stem / "progress.json"
            registry[case_id] = data.record(case_id)["family"]
            rollout = rollout_case(
                data, case_id, predictor,
                trajectory_output=trajectory_path,
                progress_output=progress_path,
                progress_every=25,
            )
            known = data.known_inputs(case_id)
            length_m, speed_mps = _characteristic_scales(known)
            expected_frames = len(data.times(case_id)) - 1
            if int(rollout.get("expected_frames", -1)) != expected_frames:
                raise ValueError("rollout did not cover the registered full horizon")
            score = score_case(
                rollout["position_rmse"], rollout["velocity_rmse"],
                expected_frames=expected_frames, length_m=length_m, speed_mps=speed_mps,
                executed=rollout["executed"], failure_category=rollout.get("failure_category"),
            )
            trajectory_ref = {
                "path": trajectory_path.relative_to(output_root).as_posix(),
                "sha256": digest(trajectory_path), "bytes": trajectory_path.stat().st_size,
            }
            progress_ref = None
            if progress_path.is_file():
                progress_ref = {
                    "path": progress_path.relative_to(output_root).as_posix(),
                    "sha256": digest(progress_path), "bytes": progress_path.stat().st_size,
                }
            rollout = dict(rollout)
            rollout["trajectory_output"] = trajectory_ref["path"]
            rollout["progress_output"] = progress_ref["path"] if progress_ref else None
            case_rows[case_id] = {
                "case_id": case_id, "trajectory": trajectory_ref, "progress": progress_ref,
                "rollout": rollout, "score": score,
            }
            score_rows[case_id] = rollout

    manifest_payload = _load_json(manifest_path, description="portable manifest")
    model_kind = payload.get("model_kind")
    dataset_id = manifest_payload.get("dataset_id")
    bundle_sha256 = digest(bundle_path)
    score_payload = {
        "schema": MODEL_SCORE_SCHEMA, "model_kind": model_kind,
        "seed": int(payload.get("seed", -1)), "hidden": int(payload.get("hidden", -1)),
        "checkpoint_sha256": checkpoint_row["sha256"], "bundle_sha256": bundle_sha256,
        "dataset_id": dataset_id, "manifest_sha256": digest(manifest_path),
        "reproduction_host": platform.node(), "source_host": source_host,
        "predictor_future_state_inputs": False,
        "future_reference_state_used_by_oracle": True,
        "cases": score_rows,
        "metrics": aggregate_cases(registry, {case_id: case_rows[case_id]["score"]
                                                for case_id in selected}),
    }
    score_path = output_root / "scores.json"
    atomic_json(score_path, score_payload)
    score_ref = {"path": score_path.relative_to(output_root).as_posix(),
                 "sha256": digest(score_path), "bytes": score_path.stat().st_size}
    full_horizon = all(row["rollout"].get("finite_rollout_complete") is True
                       for row in case_rows.values())
    report = {
        "schema": MODEL_REPRODUCTION_SCHEMA, "mode": "checkpoint_backed",
        "passed": bool(source_verification["passed"] and full_horizon),
        "full_horizon_reproduction": bool(full_horizon),
        "full_product_reproduction": False, "cross_host_reproduction": False,
        "scientific_status": "not_assessed",
        "predictor_future_state_inputs": False,
        "future_reference_state_used_by_oracle": True,
        "source_host": source_host, "reproduction_host": platform.node(),
        "data_root": str(root),
        "manifest": {"path": str(manifest_path), "sha256": digest(manifest_path)},
        "manifest_sha256": digest(manifest_path),
        "dataset_manifest_sha256": dataset_manifest_sha256,
        "dataset_id": dataset_id,
        "bundle_sha256": bundle_sha256,
        "checkpoint": {**checkpoint_row, "path": checkpoint_row["path"]},
        "checkpoint_sha256": checkpoint_row["sha256"],
        "checkpoint_registry_sha256": checkpoint_row["registry_sha256"],
        "model_kind": model_kind, "seed": int(payload.get("seed", -1)),
        "hidden": int(payload.get("hidden", -1)), "update": int(payload.get("update", -1)),
        "code": _code_evidence(), "environment": _environment_evidence(),
        "resource": {**_resource_evidence(device),
                      "wall_seconds": float(time.monotonic() - started)},
        "bundle_verification": bundle_verification,
        "verification": source_verification,
        "case_ids": list(selected), "cases": case_rows,
        "score_artifact": score_ref,
        "full_horizon": {"requested_maximum_steps": None,
                         "trajectory_frames": {case_id: int(row["rollout"]["expected_frames"] + 1)
                                                for case_id, row in case_rows.items()}},
        "comparison": {"status": "not_requested"},
    }
    # The report's artifact root is explicit because a caller may place the
    # receipt outside the output directory. It is host-local evidence, not a
    # portable identity.
    report["artifact_root"] = str(output_root)
    atomic_json(report_path, report)
    if paired_report is not None:
        comparison = _compare_paired_reproduction(report, report_path, paired_report)
        report["comparison"] = comparison
        report["cross_host_reproduction"] = bool(comparison["passed"] and comparison["distinct_host_evidence"])
        report["full_product_reproduction"] = bool(
            report["passed"] and report["cross_host_reproduction"] and comparison["passed"])
        report["passed"] = bool(report["passed"] and comparison["passed"])
        if report["source_host"] is None and comparison.get("observed_hosts"):
            report["source_host"] = next((host for host in comparison["observed_hosts"]
                                          if host != report["reproduction_host"]), None)
        atomic_json(report_path, report)
    return report


def reproduce(manifest, data_root, case_ids=None, source_host=None, *, checkpoint=None,
              output_dir=None, device="cpu", paired_report=None, report_path=None):
    if checkpoint is not None:
        return _reproduce_checkpoint(
            manifest, data_root, case_ids, source_host,
            checkpoint=checkpoint, output_dir=output_dir, device=device,
            paired_report=paired_report, report_path=report_path,
        )
    if any(value is not None for value in (output_dir, paired_report, report_path)) or device != "cpu":
        raise ValueError("reader reproduction does not accept model reproduction options")
    root = Path(data_root).resolve()
    manifest_path = _manifest_path(manifest, root)
    result = verify_dataset(manifest_path, root, case_ids=case_ids)
    # Source assets come exclusively from the supplied root; known inputs are embedded.
    with open_dataset(manifest_path, root) as data:
        for case in case_ids or data.case_ids():
            row = data.record(case)
            (root / row["hdf5"]).resolve().relative_to(root)
    return {"schema": "core.reader_reproduction.v1", "passed": result["passed"],
            "source_host": source_host, "reproduction_host": platform.node(), "data_root": str(root),
            "verification": result, "scope": "reader, full-axis oracle, hashes; GPU model reproduction is separate",
            "full_product_reproduction": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("import-f3")
    p.add_argument("--source-manifest", type=Path, required=True)
    p.add_argument("--data-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--inline-v1", action="store_true", help="legacy diagnostic only: embeds large control arrays")
    p.add_argument("--asset-dir", type=Path)
    for command in ("inspect", "verify", "reproduce"):
        p = sub.add_parser(command)
        p.add_argument("--manifest", type=Path, required=True)
        p.add_argument("--data-root", type=Path, required=True)
        p.add_argument("--output", type=Path)
        if command != "inspect":
            p.add_argument("--case-id", action="append")
        if command == "verify":
            p.add_argument("--full-scan", action="store_true")
        if command == "reproduce":
            p.add_argument("--source-host")
            p.add_argument("--checkpoint", type=Path,
                           help="registered bundle checkpoint; enables full-horizon model reproduction")
            p.add_argument("--output-dir", type=Path,
                           help="immutable-output sibling directory for model trajectories and receipts")
            p.add_argument("--device", default="cpu")
            p.add_argument("--paired-report", type=Path,
                           help="prior model reproduction report from a distinct host")
    p = sub.add_parser("phase-plan")
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--data-root", type=Path, required=True)
    p.add_argument("--case-id", action="append")
    p.add_argument("--output", type=Path)
    # Delegate without silently swallowing unsupported flags.
    for command in ("train", "profile", "rollout", "evaluate", "evaluate-checkpoints"):
        sub.add_parser(command, add_help=False).add_argument("args", nargs=argparse.REMAINDER)
    if len(sys.argv) > 1 and sys.argv[1] in ("train", "profile", "rollout", "evaluate", "evaluate-checkpoints"):
        from scripts import core_learning
        sys.argv[0] = "core_learning"
        return core_learning.main()
    args = parser.parse_args()
    if args.command == "import-f3":
        result = import_f3_manifest(args.source_manifest, args.data_root, compact=not args.inline_v1,
                                    asset_dir=args.asset_dir)
    elif args.command == "inspect":
        result = inspect_dataset(args.manifest, args.data_root)
    elif args.command == "verify":
        result = verify_dataset(args.manifest, args.data_root, case_ids=args.case_id, full_scan=args.full_scan)
    elif args.command == "phase-plan":
        result = phase_plan(args.manifest, args.data_root, case_ids=args.case_id)
    else:
        result = reproduce(args.manifest, args.data_root, args.case_id, args.source_host,
                           checkpoint=args.checkpoint, output_dir=args.output_dir,
                           device=args.device, paired_report=args.paired_report,
                           report_path=args.output if args.checkpoint is not None else None)
    if args.output:
        atomic_json(args.output, result)
    print(json.dumps({key: value for key, value in result.items() if key not in ("cases", "verification")}, indent=2))
    return 0 if result.get("passed", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
