#!/usr/bin/env python3
"""Build and verify the planning-only Core formal-training contract.

This module is deliberately static.  It parses the current training sources,
binds their hashes, and writes a nine-run/zero-credit planning receipt.  It
does not import the trainer, construct a model, read a dataset, start an
optimizer, launch a job, use a GPU/solver, or write the registry/ledger.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


LAB_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = LAB_ROOT.parent
DEFAULT_NAMESPACE = "core-v1/learning/training-contract-v1"
DEFAULT_CONTRACT = LAB_ROOT / "campaigns/core-v1/learning/training-contract-v1/contract.json"
DEFAULT_RECEIPT = LAB_ROOT / "campaigns/core-v1/learning/training-contract-v1/planning-receipt.json"
DEFAULT_CONTRACT_SHA256 = DEFAULT_CONTRACT.with_name(DEFAULT_CONTRACT.name + ".sha256")
DEFAULT_RECEIPT_SHA256 = DEFAULT_RECEIPT.with_name(DEFAULT_RECEIPT.name + ".sha256")

SCHEMA = "core.training_contract.v1"
RECEIPT_SCHEMA = "core.training_contract.planning_receipt.v1"
MODELS = ("mlp", "graph_raw", "graph_residual")
SEEDS = (17, 29, 43)
UPDATES = 32000
MILESTONES = (8000, 16000, 24000, 32000)
CENTERS = 256
HIDDEN = 64
RADIUS_OVER_H = 2.0
MAX_NEIGHBORS = 64
OPTIMIZER = "Adam"
LEARNING_RATE = 1e-3
TARGET_NORMALIZATION = "raw_dual_increment_train_shared"
CHECKPOINT_BINDINGS = (
    "model_state",
    "optimizer_state",
    "rng_state",
    "sampler_state",
    "normalization",
)

SOURCE_RELS = (
    "../PLAN.md",
    "scripts/core_training_contract.py",
    "scripts/core_learning.py",
    "scripts/core_formal_planner.py",
    "scripts/core_models.py",
    "scripts/core_contract.py",
)


class TrainingContractError(ValueError):
    """Raised when a contract or receipt fails closed."""


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _write_sha256(path: Path, source: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{sha256_file(source)}  {source.name}\n", encoding="utf-8")


def _load_json(path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TrainingContractError(f"cannot read JSON: {path}") from error
    if not isinstance(payload, dict):
        raise TrainingContractError(f"JSON root must be an object: {path}")
    return payload


def _literal_assignments(path: Path) -> dict[str, Any]:
    """Extract literal module assignments without importing ML dependencies."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as error:
        raise TrainingContractError(f"source is not parseable: {path}") from error
    values: dict[str, Any] = {}
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        if len(targets) != 1 or not isinstance(targets[0], ast.Name):
            continue
        try:
            values[targets[0].id] = ast.literal_eval(node.value)
        except (ValueError, TypeError):
            continue
    return values


def _function_source(path: Path, function_name: str) -> str:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            lines = text.splitlines(keepends=True)
            return "".join(lines[node.lineno - 1 : node.end_lineno])
    raise TrainingContractError(f"function not found: {path}:{function_name}")


def expected_run_ids() -> tuple[str, ...]:
    return tuple(f"{model}-seed{seed}" for model in MODELS for seed in SEEDS)


def _source_ref(root: Path, relative: str) -> dict[str, Any]:
    path = (root / relative).resolve()
    if not path.is_file():
        raise TrainingContractError(f"required source is missing: {relative}")
    return {
        "path": relative,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def inspect_training_sources(root: str | Path = LAB_ROOT) -> dict[str, Any]:
    """Return source-level observations for the fixed training contract."""
    root = Path(root).expanduser().resolve()
    learning = root / "scripts/core_learning.py"
    planner = root / "scripts/core_formal_planner.py"
    models = root / "scripts/core_models.py"
    learning_values = _literal_assignments(learning)
    planner_values = _literal_assignments(planner)
    model_values = _literal_assignments(models)
    checkpoint_source = _function_source(learning, "save_training_checkpoint")
    learning_text = learning.read_text(encoding="utf-8")

    observations = {
        "models": list(model_values.get("MODEL_KINDS", ())),
        "seeds": list(planner_values.get("SEEDS", ())),
        "updates": {
            "trainer": learning_values.get("DEFAULT_UPDATES"),
            "planner": planner_values.get("UPDATES"),
        },
        "milestones": {
            "trainer": list(learning_values.get("MILESTONE_UPDATES", ())),
            "planner": list(planner_values.get("MILESTONES", ())),
        },
        "centers": {
            "trainer": learning_values.get("DEFAULT_CENTERS"),
            "planner": planner_values.get("CENTERS"),
        },
        "hidden": {
            "trainer": learning_values.get("DEFAULT_HIDDEN"),
            "planner": planner_values.get("HIDDEN"),
        },
        "radius_over_h": {
            "trainer": 2.0 if '"radius_over_h": 2.0' in learning_text else None,
            "config_literal_present": '"radius_over_h": 2.0' in learning_text,
        },
        "max_neighbors": {
            "trainer": learning_values.get("DEFAULT_MAX_NEIGHBORS"),
            "config_literal_present": '"max_neighbors": DEFAULT_MAX_NEIGHBORS' in learning_text,
        },
        "optimizer": {
            "config_literal_present": '"optimizer": "Adam"' in learning_text,
            "constructor_present": "torch.optim.Adam(model.parameters(), lr=float(learning_rate))"
            in learning_text,
        },
        "learning_rate": {
            "trainer": learning_values.get("DEFAULT_LR"),
            "planner": planner_values.get("LEARNING_RATE"),
        },
        "target_normalization": {
            "config_literal_present": f'"target_normalization": "{TARGET_NORMALIZATION}"' in learning_text,
        },
        "checkpoint_bindings": {
            binding: binding in checkpoint_source for binding in CHECKPOINT_BINDINGS
        },
        "milestone_checkpoint_ledger": all(
            marker in learning_text
            for marker in ("milestone_checkpoints", "milestone_evaluation_plan", "MILESTONE_UPDATES")
        ),
    }
    return observations


def _expected_observations() -> dict[str, Any]:
    return {
        "models": list(MODELS),
        "seeds": list(SEEDS),
        "updates": {"trainer": UPDATES, "planner": UPDATES},
        "milestones": {"trainer": list(MILESTONES), "planner": list(MILESTONES)},
        "centers": {"trainer": CENTERS, "planner": CENTERS},
        "hidden": {"trainer": HIDDEN, "planner": HIDDEN},
        "radius_over_h": {"trainer": RADIUS_OVER_H, "config_literal_present": True},
        "max_neighbors": {"trainer": MAX_NEIGHBORS, "config_literal_present": True},
        "optimizer": {"config_literal_present": True, "constructor_present": True},
        "learning_rate": {"trainer": LEARNING_RATE, "planner": LEARNING_RATE},
        "target_normalization": {"config_literal_present": True},
        "checkpoint_bindings": {binding: True for binding in CHECKPOINT_BINDINGS},
        "milestone_checkpoint_ledger": True,
    }


def _observation_mismatches(observed: Mapping[str, Any]) -> list[str]:
    expected = _expected_observations()
    mismatches: list[str] = []
    for section, expected_value in expected.items():
        actual_value = observed.get(section)
        if section == "radius_over_h":
            # The trainer intentionally stores the value in the run config,
            # rather than exposing a separate DEFAULT_RADIUS_OVER_H constant.
            if actual_value != expected_value:
                mismatches.append(section)
            continue
        if actual_value != expected_value:
            if section == "checkpoint_bindings" and isinstance(actual_value, Mapping):
                mismatches.extend(
                    f"checkpoint_bindings.{key}"
                    for key, value in actual_value.items()
                    if value is not True
                )
            else:
                mismatches.append(section)
    return mismatches


def build_contract(root: str | Path = LAB_ROOT, *, namespace: str = DEFAULT_NAMESPACE) -> dict[str, Any]:
    """Build the immutable semantic contract and current source closure."""
    root = Path(root).expanduser().resolve()
    observations = inspect_training_sources(root)
    source_bindings = [_source_ref(root, relative) for relative in SOURCE_RELS]
    expected_runs = list(expected_run_ids())
    return {
        "schema": SCHEMA,
        "namespace": namespace,
        "status": "planning_only",
        "matrix": {
            "models": list(MODELS),
            "seeds": list(SEEDS),
            "expected_run_count": len(expected_runs),
            "expected_run_ids": expected_runs,
        },
        "training": {
            "updates": UPDATES,
            "milestones": list(MILESTONES),
            "loss_centers": CENTERS,
            "hidden": HIDDEN,
            "radius_over_h": RADIUS_OVER_H,
            "max_neighbors": MAX_NEIGHBORS,
            "optimizer": OPTIMIZER,
            "learning_rate": LEARNING_RATE,
            "target_normalization": TARGET_NORMALIZATION,
            "normalization_source_split": "train",
        },
        "checkpoint": {
            "required_bindings": list(CHECKPOINT_BINDINGS),
            "milestone_updates": list(MILESTONES),
            "binding_semantics": {
                "model_state": "model parameters at every resumable checkpoint",
                "optimizer_state": "Adam optimizer state",
                "rng_state": "Python/NumPy/Torch RNG state",
                "sampler_state": "transition sampler state and draw progress",
                "normalization": "train-only feature/target normalization statistics",
            },
        },
        "source_closure": {
            "source_bindings": source_bindings,
            "observations": observations,
            "observation_mismatches": _observation_mismatches(observations),
        },
        "execution_policy": {
            "planning_only": True,
            "formal_training_allowed": False,
            "formal_job_count": 0,
            "credit": 0,
            "qualification_claim": "none",
            "training_started": False,
            "optimizer_started": False,
            "gpu_started": False,
            "solver_started": False,
            "registry_written": False,
            "ledger_written": False,
        },
    }


def _ref(path: Path, root: Path) -> dict[str, Any]:
    return {"path": _relative(path, root), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def build_receipt(
    contract: Mapping[str, Any],
    *,
    contract_path: str | Path,
    root: str | Path = LAB_ROOT,
    namespace: str = DEFAULT_NAMESPACE,
) -> dict[str, Any]:
    root = Path(root).expanduser().resolve()
    contract_path = Path(contract_path).expanduser().resolve()
    if not contract_path.is_file():
        raise TrainingContractError(f"contract is missing: {contract_path}")
    source_closure = contract.get("source_closure")
    if not isinstance(source_closure, Mapping):
        raise TrainingContractError("contract has no source closure")
    return {
        "schema": RECEIPT_SCHEMA,
        "namespace": namespace,
        "status": "planning_only",
        "planning_only": True,
        "formal_training_allowed": False,
        "formal_job_count": 0,
        "credit": 0,
        "qualification_claim": "none",
        "contract": _ref(contract_path, root),
        "source_closure": {
            "source_bindings": source_closure["source_bindings"],
            "observation_mismatches": source_closure["observation_mismatches"],
        },
        "execution_constraints": {
            "read_only": True,
            "training_started": False,
            "optimizer_started": False,
            "gpu_started": False,
            "solver_started": False,
            "registry_written": False,
            "ledger_written": False,
        },
        "matrix": contract["matrix"],
        "training": contract["training"],
        "checkpoint": contract["checkpoint"],
    }


def _hash_sidecar_matches(path: Path) -> bool:
    if not path.is_file() or not path.with_name(path.name + ".sha256").is_file():
        return True
    token = path.with_name(path.name + ".sha256").read_text(encoding="utf-8").split()
    return bool(token) and token[0] == sha256_file(path)


def verify_contract(
    contract: Mapping[str, Any] | str | Path,
    *,
    root: str | Path = LAB_ROOT,
) -> dict[str, Any]:
    root = Path(root).expanduser().resolve()
    payload = _load_json(contract) if isinstance(contract, (str, Path)) else dict(contract)
    mismatches: list[str] = []
    if payload.get("schema") != SCHEMA:
        mismatches.append("schema")
    if payload.get("status") != "planning_only":
        mismatches.append("status")
    if payload.get("matrix", {}).get("models") != list(MODELS):
        mismatches.append("matrix.models")
    if payload.get("matrix", {}).get("seeds") != list(SEEDS):
        mismatches.append("matrix.seeds")
    if payload.get("matrix", {}).get("expected_run_count") != 9:
        mismatches.append("matrix.expected_run_count")
    if payload.get("matrix", {}).get("expected_run_ids") != list(expected_run_ids()):
        mismatches.append("matrix.expected_run_ids")
    expected_training = {
        "updates": UPDATES,
        "milestones": list(MILESTONES),
        "loss_centers": CENTERS,
        "hidden": HIDDEN,
        "radius_over_h": RADIUS_OVER_H,
        "max_neighbors": MAX_NEIGHBORS,
        "optimizer": OPTIMIZER,
        "learning_rate": LEARNING_RATE,
        "target_normalization": TARGET_NORMALIZATION,
        "normalization_source_split": "train",
    }
    if payload.get("training") != expected_training:
        mismatches.append("training")
    checkpoint = payload.get("checkpoint")
    if not isinstance(checkpoint, Mapping):
        mismatches.append("checkpoint")
    else:
        if checkpoint.get("required_bindings") != list(CHECKPOINT_BINDINGS):
            mismatches.append("checkpoint.required_bindings")
        if checkpoint.get("milestone_updates") != list(MILESTONES):
            mismatches.append("checkpoint.milestone_updates")
    source_closure = payload.get("source_closure")
    if not isinstance(source_closure, Mapping):
        mismatches.append("source_closure")
    else:
        observed = source_closure.get("observations")
        if not isinstance(observed, Mapping):
            mismatches.append("source_closure.observations")
        else:
            mismatches.extend(f"source_closure.observations.{path}" for path in _observation_mismatches(observed))
        bindings = source_closure.get("source_bindings")
        if not isinstance(bindings, list) or [item.get("path") for item in bindings] != list(SOURCE_RELS):
            mismatches.append("source_closure.source_bindings")
        else:
            for item in bindings:
                path = root / str(item["path"])
                if not path.is_file():
                    mismatches.append(f"source:{item['path']}:missing")
                    continue
                if item.get("bytes") != path.stat().st_size:
                    mismatches.append(f"source:{item['path']}:bytes")
                if item.get("sha256") != sha256_file(path):
                    mismatches.append(f"source:{item['path']}:sha256")
    policy = payload.get("execution_policy")
    expected_policy = build_contract(root)["execution_policy"]
    if policy != expected_policy:
        mismatches.append("execution_policy")
    return {
        "ok": not mismatches,
        "mismatches": mismatches,
        "status": "planning_only" if not mismatches else "invalid",
        "formal_training_allowed": False,
        "formal_job_count": 0,
        "credit": 0,
    }


def verify_receipt(
    receipt: Mapping[str, Any] | str | Path,
    *,
    root: str | Path = LAB_ROOT,
    contract_path: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(root).expanduser().resolve()
    receipt_path = Path(receipt).expanduser().resolve() if isinstance(receipt, (str, Path)) else None
    payload = _load_json(receipt) if receipt_path is not None else dict(receipt)
    mismatches: list[str] = []
    if payload.get("schema") != RECEIPT_SCHEMA:
        mismatches.append("schema")
    if payload.get("namespace") != DEFAULT_NAMESPACE:
        mismatches.append("namespace")
    for key, expected in (
        ("status", "planning_only"),
        ("planning_only", True),
        ("formal_training_allowed", False),
        ("formal_job_count", 0),
        ("credit", 0),
        ("qualification_claim", "none"),
    ):
        if payload.get(key) != expected:
            mismatches.append(key)
    constraints = payload.get("execution_constraints")
    if not isinstance(constraints, Mapping) or any(value is not False and key != "read_only"
                                                  for key, value in constraints.items()) \
            or constraints.get("read_only") is not True:
        mismatches.append("execution_constraints")
    contract_ref = payload.get("contract")
    if not isinstance(contract_ref, Mapping):
        mismatches.append("contract")
        contract = None
    else:
        path = Path(str(contract_ref.get("path")))
        if contract_path is not None:
            requested = Path(contract_path).expanduser().resolve()
            referenced = path if path.is_absolute() else (root / path).resolve()
            if referenced != requested:
                mismatches.append("contract.path")
        contract = _load_json(path if path.is_absolute() else root / path) if (path.is_absolute() or (root / path).is_file()) else None
        actual_path = path if path.is_absolute() else root / path
        if contract is None:
            mismatches.append("contract.path")
        else:
            if contract_ref.get("bytes") != actual_path.stat().st_size:
                mismatches.append("contract.bytes")
            if contract_ref.get("sha256") != sha256_file(actual_path):
                mismatches.append("contract.sha256")
            if not _hash_sidecar_matches(actual_path):
                mismatches.append("contract.sha256_sidecar")
            contract_report = verify_contract(contract, root=root)
            mismatches.extend(f"contract.{item}" for item in contract_report["mismatches"])
            if payload.get("matrix") != contract.get("matrix"):
                mismatches.append("matrix")
            if payload.get("training") != contract.get("training"):
                mismatches.append("training")
            if payload.get("checkpoint") != contract.get("checkpoint"):
                mismatches.append("checkpoint")
            expected_bindings = contract.get("source_closure", {}).get("source_bindings")
            if payload.get("source_closure", {}).get("source_bindings") != expected_bindings:
                mismatches.append("source_closure.source_bindings")
    if receipt_path is not None and not _hash_sidecar_matches(receipt_path):
        mismatches.append("receipt.sha256")
    return {
        "ok": not mismatches,
        "mismatches": mismatches,
        "status": "planning_only" if not mismatches else "invalid",
        "formal_training_allowed": False,
        "formal_job_count": 0,
        "credit": 0,
    }


def write_bundle(
    *,
    root: str | Path = LAB_ROOT,
    contract_path: str | Path = DEFAULT_CONTRACT,
    receipt_path: str | Path = DEFAULT_RECEIPT,
) -> dict[str, Any]:
    root = Path(root).expanduser().resolve()
    contract_path = Path(contract_path).expanduser().resolve()
    receipt_path = Path(receipt_path).expanduser().resolve()
    contract = build_contract(root)
    _write_json(contract_path, contract)
    _write_sha256(DEFAULT_CONTRACT_SHA256 if contract_path == DEFAULT_CONTRACT else contract_path.with_name(contract_path.name + ".sha256"), contract_path)
    receipt = build_receipt(contract, contract_path=contract_path, root=root)
    _write_json(receipt_path, receipt)
    _write_sha256(DEFAULT_RECEIPT_SHA256 if receipt_path == DEFAULT_RECEIPT else receipt_path.with_name(receipt_path.name + ".sha256"), receipt_path)
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    write = sub.add_parser("write", help="write the planning-only contract and receipt")
    write.add_argument("--root", type=Path, default=LAB_ROOT)
    write.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    write.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    verify = sub.add_parser("verify", help="verify the planning-only receipt")
    verify.add_argument("--root", type=Path, default=LAB_ROOT)
    verify.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    verify.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "write":
        receipt = write_bundle(root=args.root, contract_path=args.contract, receipt_path=args.receipt)
        print(json.dumps({"status": receipt["status"], "formal_job_count": 0, "credit": 0}, sort_keys=True))
        return 0
    report = verify_receipt(args.receipt, root=args.root, contract_path=args.contract)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
