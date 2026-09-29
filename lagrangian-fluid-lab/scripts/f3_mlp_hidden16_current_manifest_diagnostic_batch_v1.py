#!/usr/bin/env python3
"""Bounded multi-case diagnostic launcher for the current F3 MLP manifest.

The existing current-manifest MLP launcher is intentionally a one-case
boundary.  This additive adapter composes that boundary without changing its
formal interfaces: every selected case gets a fresh namespace, a unique
process-exit proof, a case-bound HDF5 validator receipt, and an artifact
identity sidecar.  Each case runs in an isolated worker process so the legacy
engine's temporary module constants cannot cross case boundaries.

Only the explicit non-formal current manifest, one completed ``core.training.v1``
receipt, and its declared checkpoint are accepted.  The manifest HDF5 files
are lstat/size checked before launch and again in the worker; their contents
are opened only by the diagnostic evaluator and the read-only validator.

The adapter never writes a registry, ledger, denominator, gate, PLAN, or
completion record.  It never sends a signal to an existing process and never
restarts one.  All reports and terminal artifacts are permanently diagnostic
and zero-credit.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.dont_write_bytecode = True

from scripts import f3_full_rollout_receipt_hdf5_validator_v1 as validator
from scripts import f3_mlp_hidden16_current_manifest_rollout_launcher_v1 as single
from scripts import f3_mlp_hidden16_diagnostic_rollout_launcher_v1 as legacy


LAB_ROOT = Path(__file__).resolve().parents[1]
MODEL = "mlp"
HIDDEN = 16
UPDATES = 500
TRANSITIONS = 835
FRAMES = 836
GPU_COUNT = 8
ESTIMATED_VRAM_MIB = 4096
MIN_FREE_MIB = 8192
EXPECTED_CASE_COUNT = 32
SEEDS = (17, 29, 43)
CASE_ID_RE = re.compile(r"^F3_DEV_[0-9]{2}_[A-Za-z0-9p]+$")
BATCH_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")
SCHEMA = "core.f3.mlp.hidden16.current_manifest.diagnostic_batch.v1"
REPORT_ID = "f3-mlp-hidden16-current-manifest-diagnostic-batch-v1"

ZERO_CREDIT = {
    "diagnostic_only": True,
    "formal": False,
    "formal_eligible": False,
    "T1_numerical": False,
    "T2_macro": False,
    "T2_path": False,
    "qualification": False,
    "qualification_credit": 0,
    "credit": 0,
}


class BatchError(ValueError):
    """Malformed, drifting, occupied, or resource-inadmissible batch input."""


def _fail(message: str) -> None:
    raise BatchError(f"fail-closed: {message}")


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{name} must be an object")
    return value


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        _fail(f"{name} must be a non-empty string")
    return value


def _integer(value: Any, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _fail(f"{name} must be an integer >= {minimum}")
    return value


def _boolean(value: Any, name: str) -> bool:
    if type(value) is not bool:
        _fail(f"{name} must be a boolean")
    return value


def _sha(value: Any, name: str) -> str:
    result = _string(value, name)
    if re.fullmatch(r"[0-9a-f]{64}", result) is None:
        _fail(f"{name} must be a lowercase SHA-256 digest")
    return result


def _exact(value: Mapping[str, Any], key: str, expected: Any, name: str) -> None:
    if key not in value:
        _fail(f"{name}.{key} is missing")
    observed = value[key]
    if isinstance(expected, bool) and type(observed) is not bool:
        _fail(f"{name}.{key} must be boolean")
    if type(expected) is int and type(observed) is not int:
        _fail(f"{name}.{key} must be integer")
    if observed != expected:
        _fail(f"{name}.{key} must be {expected!r}")


def _zero_credit(value: Mapping[str, Any], name: str) -> None:
    for key, expected in ZERO_CREDIT.items():
        if key in value:
            _exact(value, key, expected, name)


def _finite_json(value: Any, name: str = "value", depth: int = 0) -> None:
    if depth > 64:
        _fail(f"{name} exceeds maximum JSON depth")
    if value is None or isinstance(value, (bool, str, int)):
        return
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            _fail(f"{name} contains a non-finite number")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                _fail(f"{name} contains a non-string key")
            _finite_json(item, f"{name}.{key}", depth + 1)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) > 4096:
            _fail(f"{name} contains too many array items")
        for index, item in enumerate(value):
            _finite_json(item, f"{name}[{index}]", depth + 1)
        return
    _fail(f"{name} contains unsupported type {type(value).__name__}")


def _absolute_path(value: Path | str, name: str) -> Path:
    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        _fail(f"{name} must be a non-empty path")
    path = Path(raw)
    if not path.is_absolute():
        _fail(f"{name} must be absolute")
    normalized = os.path.normpath(str(path))
    if str(path) != normalized:
        _fail(f"{name} uses a lexical path alias")
    if any(part in {".", ".."} for part in path.parts):
        _fail(f"{name} contains a path alias component")
    if normalized != "/" and normalized.endswith(os.sep):
        _fail(f"{name} has a trailing separator")
    return Path(normalized)


def _no_symlink_components(
    path: Path,
    name: str,
    *,
    require_single_link: bool = False,
) -> os.stat_result:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            info = os.lstat(current)
        except OSError as error:
            _fail(f"cannot inspect {name}: {error}")
        if stat.S_ISLNK(info.st_mode):
            _fail(f"{name} contains a symlink component")
    if not stat.S_ISREG(info.st_mode):
        _fail(f"{name} must be a regular file")
    if require_single_link and info.st_nlink != 1:
        _fail(f"{name} must be a regular single-link file")
    return info


def _canonical_sha(value: Any) -> str:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError) as error:
        _fail(f"value cannot be canonically hashed: {error}")
    return hashlib.sha256(raw).hexdigest()


def _validate_batch_id(value: str) -> str:
    if BATCH_ID_RE.fullmatch(value) is None:
        _fail("batch_id must be a short lexical identifier without path separators")
    return value


def _validate_gpu(value: int, name: str = "gpu_index") -> int:
    if type(value) is not int or not 0 <= value < GPU_COUNT:
        _fail(f"{name} must be an integer in [0, {GPU_COUNT})")
    return value


def _read_manifest(root: Path, manifest: Path | str) -> tuple[Path, Mapping[str, Any], dict[str, Any], str]:
    manifest_path = _absolute_path(manifest, "manifest")
    payload, source = single._read_bounded_json(
        manifest_path,
        root=root,
        name="manifest",
        max_bytes=single.MAX_MANIFEST_BYTES,
    )
    _exact(payload, "schema", "core.dataset.v2", "manifest")
    _exact(payload, "case_count", EXPECTED_CASE_COUNT, "manifest")
    _exact(payload, "formal_release", False, "manifest")
    cases = payload.get("cases")
    if not isinstance(cases, list) or len(cases) != EXPECTED_CASE_COUNT:
        _fail("manifest.cases must contain exactly 32 cases")
    return manifest_path, payload, source, single._canonical_manifest_sha(payload)


def _load_cases(root: Path, payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    values = payload.get("cases")
    assert isinstance(values, list)
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(values):
        case = _mapping(raw, f"manifest.cases[{index}]")
        case_id = _string(case.get("case_id"), f"manifest.cases[{index}].case_id")
        if CASE_ID_RE.fullmatch(case_id) is None:
            _fail(f"manifest.cases[{index}].case_id is invalid")
        if case_id in seen:
            _fail("manifest case identifiers are not unique")
        seen.add(case_id)
        _exact(case, "physical_case_id", case_id, f"manifest.cases[{index}]")
        _exact(case, "family", "F3", f"manifest.cases[{index}]")
        split = _string(case.get("split"), f"manifest.cases[{index}].split")
        if split not in {"train", "validation", "test"}:
            _fail(f"manifest.cases[{index}].split is invalid")
        hdf5_rel = _string(case.get("hdf5"), f"manifest.cases[{index}].hdf5")
        rel = Path(hdf5_rel)
        if rel.is_absolute() or any(part in {".", ".."} for part in rel.parts):
            _fail(f"manifest.cases[{index}].hdf5 is not a safe relative path")
        hdf5 = _absolute_path(root / rel, f"case {case_id} hdf5")
        info = _no_symlink_components(hdf5, f"case {case_id} hdf5")
        expected_bytes = _integer(case.get("bytes"), f"manifest.cases[{index}].bytes", 1)
        if info.st_size != expected_bytes:
            _fail(
                f"case {case_id} hdf5 bytes drift: manifest={expected_bytes}, actual={info.st_size}"
            )
        result.append(
            {
                "index": index,
                "case_id": case_id,
                "physical_case_id": case_id,
                "split": split,
                "evaluation_role": _string(
                    case.get("evaluation_role"), f"manifest.cases[{index}].evaluation_role"
                ),
                "hdf5": hdf5,
                "hdf5_relative": hdf5_rel,
                "hdf5_bytes": expected_bytes,
                "hdf5_manifest_sha256": _sha(
                    case.get("sha256"), f"manifest.cases[{index}].sha256"
                ),
                "known_inputs_sha256": _sha(
                    case.get("known_inputs_sha256"),
                    f"manifest.cases[{index}].known_inputs_sha256",
                ),
                "lineage_group_id": _sha(
                    case.get("lineage_group_id"),
                    f"manifest.cases[{index}].lineage_group_id",
                ),
                "scope_id": _string(case.get("scope_id"), f"manifest.cases[{index}].scope_id"),
                "qualification_case": case.get("qualification_case"),
            }
        )
        if result[-1]["qualification_case"] is not False:
            _fail(f"case {case_id} must not be a qualification case")
    return result


def _case_by_id(cases: Sequence[Mapping[str, Any]], case_ids: Sequence[str]) -> list[dict[str, Any]]:
    if not case_ids:
        _fail("at least one --case-id is required")
    if len(set(case_ids)) != len(case_ids):
        _fail("case selection contains duplicate case IDs")
    by_id = {str(case["case_id"]): dict(case) for case in cases}
    unknown = [case_id for case_id in case_ids if case_id not in by_id]
    if unknown:
        _fail(f"selected case(s) are absent from the current manifest: {unknown}")
    return [by_id[case_id] for case_id in case_ids]


def _nonce(*, manifest_sha256: str, batch_id: str, case_id: str, seed: int, run_id: str) -> str:
    material = f"{SCHEMA}|{manifest_sha256}|{batch_id}|{case_id}|{seed}|{run_id}".encode()
    value = hashlib.sha256(material).hexdigest()[:32]
    if value == "0" * 32:
        _fail("derived namespace nonce is zero")
    return value


def _case_slug(case_id: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", case_id).strip("-").lower()
    if not slug:
        _fail("case ID produced an empty namespace slug")
    return slug


def _proof_filename(*, case: Mapping[str, Any], seed: int, nonce: str) -> str:
    digest = hashlib.sha256(
        f"{case['case_id']}|{seed}|{nonce}".encode("utf-8")
    ).hexdigest()[:32]
    return (
        "F3-MLP-HIDDEN16-CURRENT-MANIFEST-DIAGNOSTIC-BATCH-"
        f"CASE{int(case['index']):02d}-SEED{seed}-{digest}-PROCESS-EXIT-PROOF-V1.json"
    )


def _command(
    *,
    python: Path,
    core_learning: Path,
    manifest: Path,
    root: Path,
    checkpoint: Path,
    case: Mapping[str, Any],
    outputs: Mapping[str, Path],
) -> tuple[str, ...]:
    return (
        str(python),
        "-u",
        str(core_learning),
        "evaluate",
        "--manifest",
        str(manifest),
        "--data-root",
        str(root),
        "--checkpoint",
        str(checkpoint),
        "--case-id",
        str(case["case_id"]),
        "--split",
        str(case["split"]),
        "--maximum-steps",
        str(TRANSITIONS),
        "--chunk-size",
        str(single.CHUNK_SIZE),
        "--device",
        "cuda:0",
        "--progress-every",
        str(single.PROGRESS_EVERY),
        "--trajectory-output",
        str(outputs["trajectory"]),
        "--progress-output",
        str(outputs["progress"]),
        "--output",
        str(outputs["evaluation"]),
        "--diagnostic",
    )


def _command_sha(command: Sequence[str], cwd: Path, env: Mapping[str, str]) -> str:
    return _canonical_sha({"argv": list(command), "cwd": str(cwd), "env_overrides": dict(env)})


@dataclass(frozen=True)
class BatchCasePlan:
    root: Path
    manifest: Path
    manifest_sha256: str
    manifest_file_sha256: str
    seed: int
    run_id: str
    case: Mapping[str, Any]
    nonce: str
    gpu_index: int
    checkpoint: Mapping[str, Any]
    training_receipt: Path
    training_receipt_sha256: str
    training_receipt_snapshot: Mapping[str, Any]
    output_namespace: Path
    trajectory_metadata: Path
    outputs: Mapping[str, Path]
    command: tuple[str, ...]
    cwd: Path
    env: Mapping[str, str]
    command_sha256: str
    legacy_plan: Any
    proof_filename: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_id": f"f3-mlp-hidden16-{self.case['case_id']}-seed{self.seed}",
            "status": "dry_run_ready",
            "launch_allowed": False,
            "case_index": self.case["index"],
            "case_id": self.case["case_id"],
            "physical_case_id": self.case["physical_case_id"],
            "split": self.case["split"],
            "evaluation_role": self.case["evaluation_role"],
            "seed": self.seed,
            "run_id": self.run_id,
            "model": MODEL,
            "hidden": HIDDEN,
            "updates": UPDATES,
            "transitions": TRANSITIONS,
            "frames": FRAMES,
            "gpu_index": self.gpu_index,
            "manifest": str(self.manifest),
            "manifest_sha256": self.manifest_sha256,
            "manifest_file_sha256": self.manifest_file_sha256,
            "case_hdf5": {
                "path": str(self.case["hdf5"]),
                "relative_path": self.case["hdf5_relative"],
                "bytes": self.case["hdf5_bytes"],
                "manifest_artifact_sha256": self.case["hdf5_manifest_sha256"],
            },
            "checkpoint": dict(self.checkpoint),
            "training_receipt": str(self.training_receipt),
            "training_receipt_sha256": self.training_receipt_sha256,
            "output_namespace": str(self.output_namespace),
            "namespace_nonce": self.nonce,
            "command": list(self.command),
            "cwd": str(self.cwd),
            "env_overrides": dict(self.env),
            "command_sha256": self.command_sha256,
            "outputs": {key: str(value) for key, value in self.outputs.items()},
            "trajectory_metadata": str(self.trajectory_metadata),
            "process_proof_filename": self.proof_filename,
            "resource_policy": {
                "estimated_vram_mib": ESTIMATED_VRAM_MIB,
                "min_free_mib": MIN_FREE_MIB,
                "gpu_sharing_allowed": True,
                "gpu_index_is_hint_only": False,
                "kill_existing_processes": False,
                "restart_existing_processes": False,
            },
            **ZERO_CREDIT,
            "zero_credit_only": True,
            "side_effects": {
                "processes_started": 0,
                "processes_stopped": 0,
                "processes_restarted": 0,
                "registry_writes": 0,
                "ledger_writes": 0,
                "denominator_writes": 0,
                "gate_writes": 0,
                "plan_writes": 0,
            },
        }


def _build_one_plan(
    *,
    root: Path,
    manifest: Path,
    manifest_sha256: str,
    manifest_file_sha256: str,
    checkpoint: Path,
    training_receipt: Path,
    run_id: str,
    seed: int,
    case: Mapping[str, Any],
    batch_id: str,
    output_root: Path,
    gpu_index: int,
    python_executable: Path | None,
) -> BatchCasePlan:
    nonce = _nonce(
        manifest_sha256=manifest_sha256,
        batch_id=batch_id,
        case_id=str(case["case_id"]),
        seed=seed,
        run_id=run_id,
    )
    namespace = output_root / (
        f"f3-mlp500-hidden16-currentmanifest-diagnostic-{batch_id}-"
        f"case{int(case['index']):02d}-{_case_slug(str(case['case_id']))}-"
        f"seed{seed}-full835-{nonce}"
    )
    proof_filename = _proof_filename(case=case, seed=seed, nonce=nonce)
    outputs = single._output_paths(namespace, root, proof_filename)
    trajectory_metadata = single._trajectory_metadata_path(namespace)
    single._validate_outputs(outputs, trajectory_metadata, root=root)

    # Reuse the already hardened one-case identity intake.  It checks the
    # actual receipt, checkpoint path/bytes, manifest canonical identity, and
    # interpreter/core-learning input snapshots before this batch builds its
    # case-specific command.
    base = single.build_plan(
        root,
        seed=seed,
        manifest=manifest,
        checkpoint=checkpoint,
        training_receipt=training_receipt,
        run_id=run_id,
        nonce=nonce,
        output_namespace=namespace,
        gpu_index=gpu_index,
        python_executable=python_executable,
    )
    command = _command(
        python=Path(base.command[0]),
        core_learning=Path(base.command[2]),
        manifest=manifest,
        root=root,
        checkpoint=checkpoint,
        case=case,
        outputs=outputs,
    )
    env = dict(base.env)
    env["CUDA_VISIBLE_DEVICES"] = str(gpu_index)
    command_sha256 = _command_sha(command, root, env)
    legacy_plan = legacy.RolloutPlan(
        root=root,
        seed=seed,
        nonce=nonce,
        namespace=namespace,
        run_id=run_id,
        command=command,
        cwd=root,
        env=env,
        command_sha256=command_sha256,
        outputs=outputs,
        manifest_sha256=manifest_sha256,
        training_manifest_sha256=manifest_sha256,
        training_receipt_sha256=base.training_receipt_sha256,
        checkpoint=dict(base.checkpoint),
        history_summary=training_receipt,
        training_matrix=training_receipt,
        proof_output=outputs["process_proof"],
        root_identity=base.legacy_plan.root_identity,
        input_snapshots=base.legacy_plan.input_snapshots,
    )
    return BatchCasePlan(
        root=root,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        manifest_file_sha256=manifest_file_sha256,
        seed=seed,
        run_id=run_id,
        case=dict(case),
        nonce=nonce,
        gpu_index=gpu_index,
        checkpoint=dict(base.checkpoint),
        training_receipt=training_receipt,
        training_receipt_sha256=base.training_receipt_sha256,
        training_receipt_snapshot=base.training_receipt_snapshot,
        output_namespace=namespace,
        trajectory_metadata=trajectory_metadata,
        outputs=outputs,
        command=command,
        cwd=root,
        env=env,
        command_sha256=command_sha256,
        legacy_plan=legacy_plan,
        proof_filename=proof_filename,
    )


def build_plans(
    *,
    root: Path | str,
    manifest: Path | str,
    checkpoint: Path | str,
    training_receipt: Path | str,
    run_id: str,
    seed: int,
    case_ids: Sequence[str],
    batch_id: str,
    output_root: Path | str = "/tmp",
    gpu_indices: Sequence[int] = (0,),
    python_executable: Path | str | None = None,
) -> list[BatchCasePlan]:
    root_path = single._root_path(root)
    seed = _integer(seed, "seed")
    if seed not in SEEDS:
        _fail(f"seed must be one of {SEEDS}")
    batch_id = _validate_batch_id(batch_id)
    run_id = single._validate_run_id(run_id)
    manifest_path, manifest_payload, manifest_source, manifest_sha256 = _read_manifest(
        root_path, manifest
    )
    cases = _load_cases(root_path, manifest_payload)
    selected = _case_by_id(cases, case_ids)
    checkpoint_path = _absolute_path(checkpoint, "checkpoint")
    training_path = _absolute_path(training_receipt, "training_receipt")
    output_root_path = _absolute_path(output_root, "output_root")
    if Path("/tmp") not in output_root_path.parents and output_root_path != Path("/tmp"):
        _fail("output_root must remain under /tmp")
    try:
        legacy._assert_no_symlink_components(
            output_root_path, "output_root", allow_missing_leaf=False
        )
    except legacy.LauncherError as error:
        _fail(str(error))
    if not output_root_path.is_dir():
        _fail("output_root must be an existing directory")
    _validate_gpu_indices(gpu_indices, len(selected))
    normalized_gpus = _expand_gpu_indices(gpu_indices, len(selected))
    python_path = None if python_executable is None else _absolute_path(python_executable, "python_executable")
    plans: list[BatchCasePlan] = []
    for case, gpu_index in zip(selected, normalized_gpus):
        plans.append(
            _build_one_plan(
                root=root_path,
                manifest=manifest_path,
                manifest_sha256=manifest_sha256,
                manifest_file_sha256=manifest_source["sha256"],
                checkpoint=checkpoint_path,
                training_receipt=training_path,
                run_id=run_id,
                seed=seed,
                case=case,
                batch_id=batch_id,
                output_root=output_root_path,
                gpu_index=gpu_index,
                python_executable=python_path,
            )
        )
    if len({plan.nonce for plan in plans}) != len(plans):
        _fail("selected plans do not have unique namespace nonces")
    if len({str(plan.outputs["evaluation"]) for plan in plans}) != len(plans):
        _fail("selected plans do not have unique output identities")
    return plans


def _validate_gpu_indices(indices: Sequence[int], count: int) -> None:
    if not indices:
        _fail("at least one gpu index is required")
    for index, gpu in enumerate(indices):
        _validate_gpu(gpu, f"gpu_indices[{index}]")
    if len(indices) not in {1, count}:
        _fail("gpu_indices must contain one shared GPU or one GPU per selected case")


def _expand_gpu_indices(indices: Sequence[int], count: int) -> tuple[int, ...]:
    _validate_gpu_indices(indices, count)
    if len(indices) == 1:
        return tuple(indices[0] for _ in range(count))
    return tuple(indices)


def _parse_nvidia_smi(text: str) -> dict[int, dict[str, int]]:
    snapshots: dict[int, dict[str, int]] = {}
    for line_number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        fields = [field.strip() for field in line.split(",")]
        if len(fields) != 5:
            _fail(f"nvidia-smi line {line_number} must contain five fields")
        try:
            index, used, free, total, utilization = (int(field) for field in fields)
        except ValueError as error:
            _fail(f"nvidia-smi line {line_number} has invalid fields: {error}")
        _validate_gpu(index, f"nvidia-smi line {line_number} GPU")
        if min(used, free, utilization) < 0 or total <= 0 or utilization > 100:
            _fail(f"nvidia-smi line {line_number} has invalid resource values")
        if used + free > total:
            _fail(f"nvidia-smi line {line_number} used+free exceeds total")
        if index in snapshots:
            _fail(f"nvidia-smi returned duplicate GPU {index}")
        snapshots[index] = {
            "index": index,
            "memory_used_mib": used,
            "memory_free_mib": free,
            "memory_total_mib": total,
            "utilization_gpu_pct": utilization,
        }
    if not snapshots:
        _fail("nvidia-smi returned no GPUs")
    return snapshots


def query_gpu_snapshot() -> dict[int, dict[str, int]]:
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,memory.used,memory.free,memory.total,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        _fail(f"nvidia-smi query failed: {error}")
    return _parse_nvidia_smi(completed.stdout)


def _admit_gpu(plan: BatchCasePlan, min_free_mib: int) -> dict[str, int]:
    min_free_mib = _integer(min_free_mib, "min_free_mib", 1)
    snapshots = query_gpu_snapshot()
    if plan.gpu_index not in snapshots:
        _fail(f"assigned GPU {plan.gpu_index} is absent from the live snapshot")
    snapshot = snapshots[plan.gpu_index]
    required = min_free_mib + ESTIMATED_VRAM_MIB
    if snapshot["memory_free_mib"] < required:
        _fail(
            f"GPU {plan.gpu_index} free VRAM {snapshot['memory_free_mib']} MiB "
            f"is below required headroom {required} MiB"
        )
    return snapshot


def _validate_hdf5_source(plan: BatchCasePlan) -> dict[str, int]:
    info = _no_symlink_components(plan.case["hdf5"], f"case {plan.case['case_id']} hdf5")
    expected = int(plan.case["hdf5_bytes"])
    if info.st_size != expected:
        _fail(
            f"case {plan.case['case_id']} hdf5 bytes drift before launch: "
            f"manifest={expected}, actual={info.st_size}"
        )
    return {
        "device": int(info.st_dev),
        "inode": int(info.st_ino),
        "mode": int(info.st_mode),
        "nlink": int(info.st_nlink),
        "bytes": int(info.st_size),
    }


def _validate_capability_paths(plan: BatchCasePlan, capability: Any) -> None:
    expected = {
        "evaluation": plan.outputs["evaluation"],
        "trajectory": plan.outputs["trajectory"],
        "validator": plan.outputs["validator"],
    }
    for key, path in expected.items():
        observed = Path(getattr(capability, key))
        if observed != path:
            _fail(f"sealed terminal capability {key} path drifted")


def _write_validator(plan: BatchCasePlan, capability: Any) -> None:
    _validate_capability_paths(plan, capability)
    result = validator.run_validation(
        plan.outputs["evaluation"],
        plan.outputs["trajectory"],
        case_id=str(plan.case["case_id"]),
        expected_transitions=TRANSITIONS,
    )
    result = _mapping(result, "validator result")
    _finite_json(result, "validator result")
    # legacy's final post-callback validation is case-bound by the worker
    # context below.  This independent call keeps malformed validator output
    # from being written even if that implementation detail changes.
    _exact(result, "passed", True, "validator result")
    _exact(result, "fail_closed", False, "validator result")
    _exact(result, "diagnostic_only", True, "validator result")
    _exact(result, "case_id", str(plan.case["case_id"]), "validator result")
    _exact(result, "expected_transitions", TRANSITIONS, "validator result")
    _exact(result, "frames_executed", TRANSITIONS, "validator result")
    _exact(result, "complete", True, "validator result")
    _exact(result, "incomplete", False, "validator result")
    _exact(result, "qualification_credit", 0, "validator result")
    legacy._exclusive_json_write(plan.outputs["validator"], result, "validator receipt")

    trajectory = single._stream_identity(plan.outputs["trajectory"], "trajectory HDF5")
    metadata = {
        "schema": single.TRAJECTORY_METADATA_SCHEMA,
        "seed": plan.seed,
        "run_id": plan.run_id,
        "case_id": plan.case["case_id"],
        "model": MODEL,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "split": plan.case["split"],
        "transitions": TRANSITIONS,
        "frames": FRAMES,
        "namespace": str(plan.output_namespace),
        "namespace_nonce": plan.nonce,
        "trajectory": trajectory,
        "stream_hash": {
            "algorithm": "sha256",
            "sha256": trajectory["sha256"],
            "bytes": trajectory["bytes"],
        },
        **ZERO_CREDIT,
        "source_bound": True,
        "future_state_inputs": False,
    }
    legacy._exclusive_json_write(plan.trajectory_metadata, metadata, "trajectory metadata")


def _write_artifact_identity(plan: BatchCasePlan, capability: Any) -> None:
    expected = {
        "evaluation": plan.outputs["evaluation"],
        "trajectory": plan.outputs["trajectory"],
        "validator": plan.outputs["validator"],
        "sidecar": plan.outputs["artifact_identity"],
        "checkpoint": Path(plan.checkpoint["path"]),
    }
    observed = {
        "evaluation": Path(capability.evaluation_json),
        "trajectory": Path(capability.trajectory_hdf5),
        "validator": Path(capability.validator_receipt),
        "sidecar": Path(capability.sidecar),
        "checkpoint": Path(capability.checkpoint),
    }
    for key, expected_path in expected.items():
        if observed[key] != expected_path:
            _fail(f"sealed artifact capability {key} path drifted")
    identity = {
        "schema": f"core.f3.mlp.hidden16.seed{plan.seed}.evaluator_artifact_identity.v1",
        "status": "completed_diagnostic",
        "seed": plan.seed,
        "run_id": plan.run_id,
        "namespace": str(plan.output_namespace),
        "namespace_nonce": plan.nonce,
        "manifest_sha256": plan.manifest_sha256,
        "training_manifest_sha256": plan.manifest_sha256,
        "training_receipt_sha256": plan.training_receipt_sha256,
        "checkpoint": dict(plan.checkpoint),
        "evaluation": single._stream_identity(observed["evaluation"], "evaluation JSON"),
        "trajectory": single._stream_identity(observed["trajectory"], "trajectory HDF5"),
        "validator": single._stream_identity(observed["validator"], "validator receipt"),
        **ZERO_CREDIT,
    }
    legacy._exclusive_json_write(plan.outputs["artifact_identity"], identity, "artifact identity")


@contextmanager
def _bind_legacy_case(plan: BatchCasePlan):
    original_case = legacy.CASE_ID
    original_proof = legacy.PROCESS_PROOF_FILENAME
    legacy.CASE_ID = str(plan.case["case_id"])
    legacy.PROCESS_PROOF_FILENAME = plan.proof_filename
    try:
        expected = legacy._output_paths(plan.output_namespace, plan.root, plan.seed)
        if expected != dict(plan.outputs):
            _fail("legacy output contract differs from batch plan")
        yield
    finally:
        legacy.CASE_ID = original_case
        legacy.PROCESS_PROOF_FILENAME = original_proof


def _execute_one(plan: BatchCasePlan, min_free_mib: int) -> dict[str, Any]:
    gpu_snapshot = _admit_gpu(plan, min_free_mib)
    source_identity = _validate_hdf5_source(plan)
    legacy._revalidate_input_snapshot(plan.training_receipt_snapshot, "training receipt input")
    with _bind_legacy_case(plan):
        result = legacy.execute_plan(
            plan.legacy_plan,
            artifact_identity_path=plan.outputs["artifact_identity"],
            terminal_validator=lambda capability: _write_validator(plan, capability),
            artifact_identity_producer=lambda capability: _write_artifact_identity(plan, capability),
        )
    if not isinstance(result, Mapping):
        _fail("legacy execution returned a non-object result")
    return {
        **dict(result),
        "case_id": plan.case["case_id"],
        "seed": plan.seed,
        "run_id": plan.run_id,
        "gpu_index": plan.gpu_index,
        "gpu_snapshot_before_launch": gpu_snapshot,
        "hdf5_source_identity": source_identity,
        "trajectory_metadata": str(plan.trajectory_metadata),
        "training_receipt": str(plan.training_receipt),
        "checkpoint": dict(plan.checkpoint),
        "process_stopped_by_adapter": 0,
        **ZERO_CREDIT,
    }


def _worker_entry(plan: BatchCasePlan, min_free_mib: int, queue: Any) -> None:
    try:
        result = _execute_one(plan, min_free_mib)
        queue.put({"case_id": plan.case["case_id"], "ok": True, "result": result})
    except BaseException as error:  # the parent must receive every worker terminal state
        queue.put(
            {
                "case_id": plan.case["case_id"],
                "ok": False,
                "result": {
                    "schema": SCHEMA,
                    "status": "blocked_worker_fail_closed",
                    "case_id": plan.case["case_id"],
                    "seed": plan.seed,
                    "gpu_index": plan.gpu_index,
                    "error": f"{type(error).__name__}: {error}",
                    "launched": False,
                    "proof_written": False,
                    "process_stopped_by_adapter": 0,
                    **ZERO_CREDIT,
                },
            }
        )


def execute_batch(
    plans: Sequence[BatchCasePlan],
    *,
    min_free_mib: int = MIN_FREE_MIB,
    worker_factory: Any | None = None,
) -> list[dict[str, Any]]:
    """Run selected cases in isolated workers and wait for natural exits only."""

    if not plans:
        _fail("cannot execute an empty batch")
    if worker_factory is not None:
        # A narrow injectable path keeps the unit tests non-GPU and does not
        # become part of the CLI surface.
        results = []
        for plan in plans:
            result = worker_factory(plan, min_free_mib)
            if not isinstance(result, Mapping):
                _fail("test worker returned a non-object result")
            results.append(dict(result))
        return results

    context = mp.get_context("spawn")
    queue = context.Queue()
    processes: list[Any] = []
    for plan in plans:
        process = context.Process(target=_worker_entry, args=(plan, min_free_mib, queue))
        process.start()
        processes.append(process)

    for process in processes:
        # Joining only waits for our newly created worker.  It does not signal,
        # stop, or restart any pre-existing process.
        process.join()

    received: dict[str, dict[str, Any]] = {}
    for _ in plans:
        try:
            message = queue.get(timeout=10)
        except Exception as error:
            _fail(f"worker terminal result missing: {error}")
        case_id = _string(message.get("case_id"), "worker.case_id")
        received[case_id] = dict(_mapping(message.get("result"), "worker.result"))
    queue.close()
    queue.join_thread()

    expected = [str(plan.case["case_id"]) for plan in plans]
    if set(received) != set(expected):
        _fail("worker result case set differs from the submitted batch")
    return [received[case_id] for case_id in expected]


def _artifact_path_identity(path: Path) -> dict[str, Any]:
    try:
        info = os.lstat(path)
    except OSError as error:
        _fail(f"cannot inspect terminal artifact {path}: {error}")
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        _fail(f"terminal artifact {path} is not a regular single-link file")
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
            total += len(block)
    if total != info.st_size:
        _fail(f"terminal artifact {path} changed while hashing")
    return {"path": str(path), "sha256": digest.hexdigest(), "bytes": total}


def _report_for(
    plans: Sequence[BatchCasePlan],
    *,
    results: Sequence[Mapping[str, Any]] | None,
    batch_id: str,
    min_free_mib: int,
    initial_gpu_snapshot: Mapping[int, Mapping[str, int]] | None,
) -> dict[str, Any]:
    result_rows = [dict(result) for result in (results or [])]
    success_count = sum(row.get("status") == "exited_successfully" for row in result_rows)
    terminal_paths = []
    for plan, row in zip(plans, result_rows):
        if row.get("status") == "exited_successfully":
            terminal_paths.append(
                {
                    "case_id": plan.case["case_id"],
                    "seed": plan.seed,
                    "process_proof": _artifact_path_identity(plan.outputs["process_proof"]),
                    "validator": _artifact_path_identity(plan.outputs["validator"]),
                    "artifact_identity": _artifact_path_identity(plan.outputs["artifact_identity"]),
                    "trajectory_metadata": _artifact_path_identity(plan.trajectory_metadata),
                }
            )
    report_status = (
        "completed_diagnostic_batch"
        if result_rows and success_count == len(plans)
        else "dry_run_ready"
        if results is None
        else "blocked_diagnostic_batch"
    )
    manifest = plans[0]
    report = {
        "schema": SCHEMA,
        "report_id": REPORT_ID,
        "status": report_status,
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "batch_id": batch_id,
        "source_bound": True,
        "manifest": {
            "path": str(manifest.manifest),
            "canonical_sha256": manifest.manifest_sha256,
            "file_sha256": manifest.manifest_file_sha256,
            "formal_release": False,
            "case_count_in_manifest": EXPECTED_CASE_COUNT,
        },
        "training": {
            "path": str(manifest.training_receipt),
            "sha256": manifest.training_receipt_sha256,
            "schema": "core.training.v1",
            "model": MODEL,
            "hidden": HIDDEN,
            "updates": UPDATES,
            "seed": manifest.seed,
            "run_id": manifest.run_id,
            "checkpoint": dict(manifest.checkpoint),
        },
        "cases": [dict(plan.case) | {"hdf5": str(plan.case["hdf5"])} for plan in plans],
        "plans": [plan.as_dict() for plan in plans],
        "results": result_rows,
        "coverage": {
            "selected_case_count": len(plans),
            "selected_case_ids": [str(plan.case["case_id"]) for plan in plans],
            "seed_count": 1,
            "seeds": [manifest.seed],
            "terminal_receipts_required": len(plans),
            "terminal_receipts_observed": success_count,
            "terminal_receipts_missing": len(plans) - success_count,
            "unique_namespaces": len({str(plan.output_namespace) for plan in plans}),
            "unique_nonces": len({plan.nonce for plan in plans}),
            "unique_command_identities": len({plan.command_sha256 for plan in plans}),
        },
        "scheduler": {
            "execution_mode": "spawned_one_worker_per_case",
            "selected_gpu_indices": [plan.gpu_index for plan in plans],
            "gpu_sharing_allowed": True,
            "min_free_mib": min_free_mib,
            "estimated_vram_mib_per_case": ESTIMATED_VRAM_MIB,
            "initial_gpu_snapshot": {
                str(index): dict(snapshot)
                for index, snapshot in (initial_gpu_snapshot or {}).items()
            },
            "existing_processes_killed": 0,
            "existing_processes_restarted": 0,
        },
        "terminal_receipts": {
            "status": "complete" if success_count == len(plans) and results is not None else "missing",
            "required_count": len(plans),
            "observed_count": success_count,
            "missing_count": len(plans) - success_count,
            "paths": terminal_paths,
        },
        "input_boundary": {
            "manifest_bounded_json_opened": True,
            "training_receipt_bounded_json_opened": True,
            "checkpoint_identity_stat_only_at_intake": True,
            "checkpoint_content_opened_by_diagnostic_evaluator": results is not None,
            "case_hdf5_lstat_size_checked": True,
            "case_hdf5_content_opened_by_diagnostic_evaluator": results is not None,
            "case_hdf5_content_opened_by_read_only_validator": results is not None,
            "registry_read": False,
            "ledger_read": False,
            "denominator_read": False,
            "gate_read": False,
            "plan_read": False,
        },
        "side_effects": {
            "worker_processes_started": len(result_rows) if results is not None else 0,
            "evaluator_processes_started": sum(bool(row.get("launched")) for row in result_rows),
            "processes_stopped": 0,
            "processes_restarted": 0,
            "registry_writes": 0,
            "ledger_writes": 0,
            "denominator_writes": 0,
            "gate_writes": 0,
            "plan_writes": 0,
        },
        "checks": {
            "real_nonformal_manifest": True,
            "real_training_receipt_identity": True,
            "real_checkpoint_identity": True,
            "selected_hdf5_paths_exist_and_match_manifest_bytes": True,
            "multiple_case_plans_have_unique_namespaces": len(plans) == len({str(plan.output_namespace) for plan in plans}),
            "all_terminal_receipts_zero_credit": all(
                row.get("credit") == 0 and row.get("diagnostic_only") is True
                for row in result_rows
            ) if results is not None else True,
            "existing_processes_untouched": True,
        },
        "blocked_reasons": [
            row.get("error")
            for row in result_rows
            if row.get("status") != "exited_successfully" and row.get("error")
        ],
        "interpretation": (
            "This is an additive F3 diagnostic batch report only. It cannot grant "
            "formal, T1, T2, qualification, denominator, ledger, registry, gate, "
            "or completion credit."
        ),
        **ZERO_CREDIT,
    }
    _validate_report(report)
    return report


def _validate_report(report: Mapping[str, Any]) -> None:
    _exact(report, "schema", SCHEMA, "report")
    _zero_credit(report, "report")
    _exact(report, "source_bound", True, "report")
    coverage = _mapping(report.get("coverage"), "report.coverage")
    required = _integer(coverage.get("terminal_receipts_required"), "report.coverage.required", 1)
    observed = _integer(coverage.get("terminal_receipts_observed"), "report.coverage.observed")
    if observed > required:
        _fail("report terminal receipt coverage exceeds required count")
    scheduler = _mapping(report.get("scheduler"), "report.scheduler")
    _exact(scheduler, "existing_processes_killed", 0, "report.scheduler")
    _exact(scheduler, "existing_processes_restarted", 0, "report.scheduler")
    side_effects = _mapping(report.get("side_effects"), "report.side_effects")
    for key in (
        "processes_stopped",
        "processes_restarted",
        "registry_writes",
        "ledger_writes",
        "denominator_writes",
        "gate_writes",
        "plan_writes",
    ):
        _exact(side_effects, key, 0, "report.side_effects")
    plans = report.get("plans")
    if not isinstance(plans, list) or not plans:
        _fail("report.plans must be a non-empty list")
    namespaces = [plan.get("output_namespace") for plan in plans if isinstance(plan, Mapping)]
    if len(namespaces) != len(set(namespaces)):
        _fail("report plan namespaces are not unique")
    results = report.get("results")
    if not isinstance(results, list):
        _fail("report.results must be a list")
    for row in results:
        _zero_credit(_mapping(row, "report.results[]"), "report.results[]")


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"


def _exclusive_write(path: Path, content: bytes) -> None:
    path = _absolute_path(path, "report output")
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o644)
    except OSError as error:
        _fail(f"cannot create report output {path}: {error}")
    try:
        offset = 0
        while offset < len(content):
            offset += os.write(fd, content[offset:])
        os.fsync(fd)
    finally:
        os.close(fd)


def render_markdown(report: Mapping[str, Any]) -> str:
    coverage = report["coverage"]
    lines = [
        "# F3 MLP hidden16 current-manifest diagnostic batch",
        "",
        f"- 状态：`{report['status']}`；batch=`{report['batch_id']}`",
        f"- 覆盖：`{coverage['selected_case_count']} real cases × seed {coverage['seeds'][0]}`",
        f"- 终态回执：`{coverage['terminal_receipts_observed']}/{coverage['terminal_receipts_required']}`；缺失 `{coverage['terminal_receipts_missing']}`",
        "- 权限：所有结果 `diagnostic_only=true`、formal/T1/T2/qualification=`false`、credit=`0`",
        "- 进程安全：只等待本批新建 worker/evaluator 自然退出；既有进程停止/重启均为 `0`",
        "",
        "## Source binding",
        "",
        f"- manifest：`{report['manifest']['path']}`",
        f"- manifest canonical SHA：`{report['manifest']['canonical_sha256']}`",
        f"- training receipt：`{report['training']['path']}`",
        f"- checkpoint：`{report['training']['checkpoint']['path']}` (`{report['training']['checkpoint']['sha256']}`)",
        "",
        "## Cases",
        "",
        "| case | split | HDF5 bytes | GPU | status | proof |",
        "|---|---|---:|---:|---|---|",
    ]
    by_case = {str(row.get("case_id")): row for row in report.get("results", [])}
    for plan in report["plans"]:
        case_id = str(plan["case_id"])
        row = by_case.get(case_id, {})
        proof = row.get("proof_path", "—")
        lines.append(
            f"| `{case_id}` | `{plan['split']}` | {plan['case_hdf5']['bytes']} | "
            f"{plan['gpu_index']} | `{row.get('status', 'dry_run_ready')}` | `{proof}` |"
        )
    lines.extend(
        [
            "",
            "该报告是独立 diagnostic evidence；不会写入 Core formal registry、ledger、denominator、gate、PLAN 或 completion 状态。",
            "",
        ]
    )
    return "\n".join(lines)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--training-receipt", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--seed", type=int, required=True, choices=SEEDS)
    parser.add_argument("--case-id", action="append", required=True)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--output-root", type=Path, default=Path("/tmp"))
    parser.add_argument("--gpu-index", type=int, action="append", default=None)
    parser.add_argument("--min-free-mib", type=int, default=MIN_FREE_MIB)
    parser.add_argument("--python-executable", type=Path, default=None)
    parser.add_argument("--output-report", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, default=None)
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        gpu_indices = tuple(args.gpu_index or (0,))
        plans = build_plans(
            root=args.root,
            manifest=args.manifest,
            checkpoint=args.checkpoint,
            training_receipt=args.training_receipt,
            run_id=args.run_id,
            seed=args.seed,
            case_ids=args.case_id,
            batch_id=args.batch_id,
            output_root=args.output_root,
            gpu_indices=gpu_indices,
            python_executable=args.python_executable,
        )
        _absolute_path(args.output_report, "output_report")
        if os.path.lexists(args.output_report):
            _fail(f"refusing to overwrite existing output report: {args.output_report}")
        if args.markdown_output is not None and os.path.lexists(args.markdown_output):
            _fail(f"refusing to overwrite existing markdown report: {args.markdown_output}")
        initial_snapshot = query_gpu_snapshot() if args.execute else {}
        if args.execute:
            results = execute_batch(plans, min_free_mib=args.min_free_mib)
        else:
            results = None
        report = _report_for(
            plans,
            results=results,
            batch_id=args.batch_id,
            min_free_mib=args.min_free_mib,
            initial_gpu_snapshot=initial_snapshot,
        )
        _exclusive_write(_absolute_path(args.output_report, "output_report"), _json_bytes(report))
        if args.markdown_output is not None:
            _exclusive_write(_absolute_path(args.markdown_output, "markdown_output"), render_markdown(report).encode())
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "cases": len(plans),
                    "terminal_receipts": report["coverage"]["terminal_receipts_observed"],
                    "credit": report["credit"],
                    "output_report": str(args.output_report),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0 if report["status"] in {"dry_run_ready", "completed_diagnostic_batch"} else 1
    except (BatchError, OSError, ValueError, RecursionError) as error:
        print(
            json.dumps(
                {
                    "schema": SCHEMA,
                    "status": "blocked_fail_closed",
                    "diagnostic_only": True,
                    "credit": 0,
                    "error": str(error),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
