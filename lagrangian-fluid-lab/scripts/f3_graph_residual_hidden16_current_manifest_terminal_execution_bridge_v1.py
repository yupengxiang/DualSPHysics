#!/usr/bin/env python3
"""Fail-closed execution boundary for the current graph_residual terminal path.

This additive bridge connects three already reviewed contracts without changing
any of them:

* the current-manifest residual launcher builds the exact command and source
  identity;
* the historical terminal runtime verifier supplies the shared
  835-transition/836-frame evidence vocabulary; and
* the current terminal-artifact identity canary validates a future real
  ``subprocess.Popen``/``wait`` proof and independent HDF5-validator receipt.

The bridge is intentionally dry-run by default.  No producer/validator
capability is admitted in this revision, so even an explicit ``--execute``
request is rejected before Popen.  A future capability may be connected only
behind this boundary and must still produce a receipt accepted by
``validate_terminal_execution_receipt``.  All outputs remain diagnostic-only
and permanently zero-credit; this module does not touch PLAN, registry,
ledger, denominator, gate, completion, solver, worker, queue, or live jobs.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.dont_write_bytecode = True

from scripts import f3_graph_residual_hidden16_current_manifest_rollout_launcher_v1 as launcher
from scripts import f3_graph_residual_hidden16_current_manifest_terminal_artifact_identity_v1 as identity
from scripts import f3_graph_residual_hidden16_terminal_runtime_verifier_v1 as runtime_verifier


LAB_ROOT = Path(__file__).resolve().parents[1]
SEEDS = identity.SEEDS
DEFAULT_GPU_INDICES = dict(identity.DEFAULT_GPU_INDICES)
MODEL = identity.MODEL
HIDDEN = identity.HIDDEN
UPDATES = identity.UPDATES
CASE_ID = identity.CASE_ID
SPLIT = identity.SPLIT
TRANSITIONS = identity.TRANSITIONS
FRAMES = identity.FRAMES
PLAN_DATE = identity.PLAN_DATE

SCHEMA = "core.f3.graph_residual.hidden16.current_manifest.terminal_execution_bridge.v1"
PLAN_SCHEMA = "core.f3.graph_residual.hidden16.current_manifest.audited_terminal_execution_bridge_plan.v1"
OBSERVATION_SCHEMA = "core.f3.graph_residual.hidden16.current_manifest.terminal_execution_observation.v1"
RECEIPT_SCHEMA = "core.f3.graph_residual.hidden16.current_manifest.terminal_execution_bridge_receipt.v1"
REPORT_SCHEMA = "core.f3.graph_residual.hidden16.current_manifest.terminal_execution_bridge_report.v1"
REPORT_ID = "f3-graph-residual-hidden16-current-manifest-terminal-execution-bridge-v1"
EXECUTION_CAPABILITY_SCHEMA = (
    "core.f3.graph_residual.hidden16.current_manifest.terminal_producer_validator_capability.v1"
)

DEFAULT_MANIFEST = identity.DEFAULT_MANIFEST
DEFAULT_RECEIPTS = dict(identity.DEFAULT_RECEIPTS)
DEFAULT_CHECKPOINTS = dict(identity.DEFAULT_CHECKPOINTS)
DEFAULT_REPORT = (
    LAB_ROOT
    / "reports"
    / "F3-GRAPH-RESIDUAL-HIDDEN16-CURRENT-MANIFEST-TERMINAL-EXECUTION-BRIDGE-2026-09-29.json"
)
DEFAULT_MARKDOWN_REPORT = DEFAULT_REPORT.with_suffix(".zh-CN.md")

ZERO_CREDIT: dict[str, Any] = {
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

_PLAN_KEYS = frozenset(
    {
        "schema",
        "seed",
        "run_id",
        "model_kind",
        "hidden",
        "updates",
        "case_id",
        "split",
        "transitions",
        "frames",
        "manifest_sha256",
        "training_receipt_sha256",
        "checkpoint",
        "namespace",
        "namespace_nonce",
        "command",
        "command_sha256",
        "gpu_index",
        "admission",
        "plan_digest",
        *ZERO_CREDIT,
    }
)
_BOUNDARY_KEYS = frozenset(
    {
        "schema",
        "mode",
        "execution_requested",
        "launch_allowed",
        "terminal_producer_admitted",
        "independent_hdf5_validator_admitted",
        "popen_allowed",
        "popen_called",
        "wait_observed",
        "validator_started",
        "execution_attempted",
        "blocked_reasons",
        *ZERO_CREDIT,
    }
)
_REPORT_KEYS = frozenset(
    {
        "schema",
        "report_id",
        "observed_at_utc",
        "status",
        "mode",
        "dry_run",
        "execution_requested",
        "source_bound",
        "terminal_source_bound",
        "launch_allowed",
        "terminal_producer_admitted",
        "independent_hdf5_validator_admitted",
        "process_proofs_verified",
        "process_proofs_expected",
        "hdf5_validators_verified",
        "hdf5_validators_expected",
        "terminal_artifacts_verified",
        "terminal_artifacts_expected",
        "expected_contract",
        "contract_review",
        "seed_rows",
        "blocked_reasons",
        "input_boundary",
        "side_effects",
        *ZERO_CREDIT,
    }
)
_ROW_KEYS = frozenset(
    {
        "seed",
        "status",
        "source_bound",
        "run_id",
        "manifest_sha256",
        "training_receipt_sha256",
        "checkpoint",
        "namespace",
        "namespace_nonce",
        "command",
        "command_sha256",
        "plan_digest",
        "gpu_index",
        "resource_admission",
        "execution_boundary",
        "process_proof",
        "hdf5_validator",
        "terminal_artifact_identity",
        "launch_allowed",
        "blocked_reasons",
    }
)


class BridgeError(ValueError):
    """Malformed, drifting, unsafe, or non-authorizing bridge input."""


def _fail(message: str) -> None:
    raise BridgeError(f"fail-closed: {message}")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{name} must be an object")
    return value


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        _fail(f"{name} must be a non-empty string")
    return value


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        _fail(f"{name} must be boolean")
    return value


def _int(value: Any, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _fail(f"{name} must be an integer >= {minimum}")
    return value


def _sha(value: Any, name: str) -> str:
    text = _string(value, name)
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        _fail(f"{name} must be a lowercase SHA-256 digest")
    return text


def _exact(value: Mapping[str, Any], key: str, expected: Any, name: str) -> None:
    if key not in value:
        _fail(f"{name}.{key} is missing")
    observed = value[key]
    if isinstance(expected, bool) and type(observed) is not bool:
        _fail(f"{name}.{key} must be boolean")
    if type(expected) is int and type(observed) is not int:
        _fail(f"{name}.{key} must be integer")
    if observed != expected:
        _fail(f"{name}.{key} must be {expected!r}; observed {observed!r}")


def _unknown(value: Mapping[str, Any], allowed: frozenset[str], name: str) -> None:
    extra = sorted(set(value) - set(allowed))
    if extra:
        _fail(f"{name} contains unknown fields: {extra}")


def _zero_credit(value: Mapping[str, Any], name: str) -> None:
    for key, expected in ZERO_CREDIT.items():
        _exact(value, key, expected, name)


def _review_contracts() -> dict[str, Any]:
    """Review shared invariants without granting runtime authority."""

    shared = {
        "model_kind": MODEL,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "case_id": CASE_ID,
        "split": SPLIT,
        "transitions": TRANSITIONS,
        "frames": FRAMES,
    }
    for module_name, module in (
        ("launcher", launcher),
        ("terminal_artifact_identity", identity),
        ("terminal_runtime_verifier", runtime_verifier),
    ):
        observed = {
            "model_kind": getattr(module, "MODEL", getattr(module, "MODEL_KIND", None)),
            "hidden": getattr(module, "HIDDEN", None),
            "updates": getattr(module, "UPDATES", None),
            "case_id": getattr(module, "CASE_ID", None),
            "split": getattr(module, "SPLIT", None),
            "transitions": getattr(module, "TRANSITIONS", None),
            "frames": getattr(module, "FRAMES", None),
        }
        if observed != shared:
            _fail(f"{module_name} shared terminal constants drift from the current bridge")

    current_run_id = identity._expected_run_id(SEEDS[0])
    historical_run_id = runtime_verifier._run_id(SEEDS[0])
    # The historical verifier deliberately uses the 2026-09-28 run-id family;
    # it is reviewed for invariant compatibility, never used as current auth.
    direct_current_manifest_admission = runtime_verifier.RUN_ID_RE.fullmatch(current_run_id) is not None
    if direct_current_manifest_admission:
        _fail("historical runtime verifier unexpectedly admits the current run-id")
    return {
        "launcher": {
            "module": launcher.__name__,
            "plan_schema": launcher.SCHEMA,
            "execute_capability_admitted": False,
            "default_launch_allowed": False,
        },
        "terminal_artifact_identity": {
            "module": identity.__name__,
            "schema": identity.SCHEMA,
            "capability_schema": identity.TERMINAL_CAPABILITY_SCHEMA,
            "execute_capability_admitted": False,
            "default_launch_allowed": False,
        },
        "terminal_runtime_verifier": {
            "module": runtime_verifier.__name__,
            "schema": runtime_verifier.REPORT_SCHEMA,
            "historical_run_id_example": historical_run_id,
            "current_run_id_example": current_run_id,
            "shared_identity_constants_match": True,
            "direct_current_manifest_admission": False,
            "used_for_current_execution_authorization": False,
        },
        "current_bridge": {
            "schema": SCHEMA,
            "execution_capability_schema": EXECUTION_CAPABILITY_SCHEMA,
            "terminal_producer_admitted": False,
            "independent_hdf5_validator_admitted": False,
        },
    }


@dataclass(frozen=True)
class BridgePlan:
    """An audited current-manifest plan with no execution authority."""

    audited: identity.AuditedPlan
    plan_digest: str
    contract_review: Mapping[str, Any]

    @property
    def seed(self) -> int:
        return self.audited.seed

    @property
    def nonce(self) -> str:
        return self.audited.nonce

    @property
    def namespace(self) -> Path:
        return self.audited.namespace


def build_bridge_plan(
    root: Path | str = LAB_ROOT,
    *,
    seed: int,
    manifest: Path | str,
    training_receipt: Path | str,
    checkpoint: Path | str,
    run_id: str | None = None,
    nonce: str,
    output_namespace: Path | str,
    gpu_index: int,
    admission: Mapping[str, Any] | None = None,
) -> BridgePlan:
    """Bind source/checkpoint/nonce/command identity without starting a job."""

    review = _review_contracts()
    if admission is None:
        admission = identity.probe_resource_admission(gpu_index)
    audited = identity.build_audited_plan(
        root,
        seed=seed,
        manifest=manifest,
        training_receipt=training_receipt,
        checkpoint=checkpoint,
        run_id=run_id or identity._expected_run_id(seed),
        nonce=nonce,
        output_namespace=output_namespace,
        gpu_index=gpu_index,
        admission=admission,
    )
    digest = canonical_digest(
        {
            "schema": PLAN_SCHEMA,
            "seed": audited.seed,
            "run_id": audited.base.run_id,
            "manifest_sha256": audited.base.manifest_binding["canonical_sha256"],
            "training_receipt_sha256": audited.base.training_binding["sha256"],
            "checkpoint": dict(audited.base.checkpoint),
            "namespace": str(audited.namespace),
            "namespace_nonce": audited.nonce,
            "command": list(audited.base.command),
            "command_sha256": audited.base.command_sha256,
            "gpu_index": audited.gpu_index,
            "admission": dict(audited.admission),
        }
    )
    return BridgePlan(audited=audited, plan_digest=digest, contract_review=review)


def _plan_projection(plan: BridgePlan) -> dict[str, Any]:
    base = plan.audited.base
    return {
        "schema": PLAN_SCHEMA,
        "seed": plan.seed,
        "run_id": base.run_id,
        "model_kind": MODEL,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "case_id": CASE_ID,
        "split": SPLIT,
        "transitions": TRANSITIONS,
        "frames": FRAMES,
        "manifest_sha256": base.manifest_binding["canonical_sha256"],
        "training_receipt_sha256": base.training_binding["sha256"],
        "checkpoint": dict(base.checkpoint),
        "namespace": str(plan.namespace),
        "namespace_nonce": plan.nonce,
        "command": list(base.command),
        "command_sha256": base.command_sha256,
        "gpu_index": plan.audited.gpu_index,
        "admission": dict(plan.audited.admission),
        "plan_digest": plan.plan_digest,
        "launch_allowed": False,
        **ZERO_CREDIT,
    }


def _blocked_boundary(
    *, execution_requested: bool, blocked: Sequence[str]
) -> dict[str, Any]:
    return {
        "schema": OBSERVATION_SCHEMA,
        "mode": "dry_run" if not execution_requested else "execute_request_rejected",
        "execution_requested": bool(execution_requested),
        "launch_allowed": False,
        "terminal_producer_admitted": False,
        "independent_hdf5_validator_admitted": False,
        "popen_allowed": False,
        "popen_called": False,
        "wait_observed": False,
        "validator_started": False,
        "execution_attempted": False,
        "blocked_reasons": list(dict.fromkeys(blocked)),
        **ZERO_CREDIT,
    }


def build_execution_boundary(plan: BridgePlan, *, execution_requested: bool = False) -> dict[str, Any]:
    """Return the only currently admitted execution decision: no launch."""

    blocked = [
        f"{EXECUTION_CAPABILITY_SCHEMA} is not implemented/admitted",
        "independent HDF5 validator producer capability is not admitted",
        "dry-run boundary forbids direct batch execution and Popen/wait",
    ]
    if not bool(plan.audited.admission.get("admitted")):
        blocked.extend(str(item) for item in plan.audited.admission.get("blocked_reasons", []))
    return _blocked_boundary(execution_requested=execution_requested, blocked=blocked)


def execute_bridge(
    plan: BridgePlan,
    *,
    execution_requested: bool = False,
    popen_factory: Any | None = None,
) -> dict[str, Any]:
    """Enforce the execute boundary; this revision never reaches Popen.

    ``popen_factory`` is accepted only so callers/tests can prove that the
    boundary ignores even a supplied launcher.  It is deliberately never
    called.  The parameter is not an execution escape hatch.
    """

    del popen_factory
    boundary = build_execution_boundary(plan, execution_requested=execution_requested)
    if execution_requested:
        _fail(
            f"{EXECUTION_CAPABILITY_SCHEMA} is not implemented/admitted; "
            "no evaluator was started and no terminal validator was started"
        )
    return boundary


def _runtime_binding(plan: BridgePlan) -> dict[str, Any]:
    review = plan.contract_review["terminal_runtime_verifier"]
    return {
        "schema": runtime_verifier.REPORT_SCHEMA,
        "model_kind": MODEL,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "case_id": CASE_ID,
        "split": SPLIT,
        "transitions": TRANSITIONS,
        "frames": FRAMES,
        "shared_identity_constants_match": True,
        "direct_current_manifest_admission": False,
        "used_for_current_execution_authorization": False,
        "historical_run_id_example": review["historical_run_id_example"],
        "current_run_id_example": plan.audited.base.run_id,
    }


def validate_terminal_execution_receipt(
    payload: Mapping[str, Any], plan: BridgePlan
) -> dict[str, Any]:
    """Validate a future real terminal envelope without minting one here."""

    value = _mapping(payload, "terminal_execution_receipt")
    _unknown(
        value,
        frozenset(
            {
                "schema",
                "status",
                "seed",
                "plan_digest",
                "manifest_sha256",
                "training_receipt_sha256",
                "namespace",
                "namespace_nonce",
                "model_kind",
                "hidden",
                "updates",
                "case_id",
                "split",
                "transitions",
                "frames",
                "runtime_verifier_binding",
                "execution_observation",
                "terminal_artifact_identity",
                *ZERO_CREDIT,
            }
        ),
        "terminal_execution_receipt",
    )
    _exact(value, "schema", RECEIPT_SCHEMA, "terminal_execution_receipt")
    _exact(value, "status", "terminal_execution_verified_diagnostic_only", "terminal_execution_receipt")
    _exact(value, "seed", plan.seed, "terminal_execution_receipt")
    _exact(value, "plan_digest", plan.plan_digest, "terminal_execution_receipt")
    _exact(value, "manifest_sha256", plan.audited.base.manifest_binding["canonical_sha256"], "terminal_execution_receipt")
    _exact(value, "training_receipt_sha256", plan.audited.base.training_binding["sha256"], "terminal_execution_receipt")
    _exact(value, "namespace", str(plan.namespace), "terminal_execution_receipt")
    _exact(value, "namespace_nonce", plan.nonce, "terminal_execution_receipt")
    for key, expected in {
        "model_kind": MODEL,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "case_id": CASE_ID,
        "split": SPLIT,
        "transitions": TRANSITIONS,
        "frames": FRAMES,
    }.items():
        _exact(value, key, expected, "terminal_execution_receipt")
    _zero_credit(value, "terminal_execution_receipt")

    runtime_binding = _mapping(value.get("runtime_verifier_binding"), "runtime_verifier_binding")
    expected_runtime = _runtime_binding(plan)
    for key, expected in expected_runtime.items():
        _exact(runtime_binding, key, expected, "runtime_verifier_binding")

    observation = _mapping(value.get("execution_observation"), "execution_observation")
    _unknown(
        observation,
        frozenset(
            {
                "schema",
                "producer",
                "synthetic",
                "popen_called",
                "wait_observed",
                "wait_returncode",
                "command_sha256",
                "argv",
                "cwd",
                "independent_validator_passed",
                "validator_returncode",
                "transitions",
                "frames",
            }
        ),
        "execution_observation",
    )
    _exact(observation, "schema", OBSERVATION_SCHEMA, "execution_observation")
    _exact(observation, "producer", "audited_terminal_producer", "execution_observation")
    _exact(observation, "synthetic", False, "execution_observation")
    _exact(observation, "popen_called", True, "execution_observation")
    _exact(observation, "wait_observed", True, "execution_observation")
    _exact(observation, "wait_returncode", 0, "execution_observation")
    _exact(observation, "command_sha256", plan.audited.base.command_sha256, "execution_observation")
    _exact(observation, "argv", list(plan.audited.base.command), "execution_observation")
    _exact(observation, "cwd", str(plan.audited.base.cwd), "execution_observation")
    _exact(observation, "independent_validator_passed", True, "execution_observation")
    _exact(observation, "validator_returncode", 0, "execution_observation")
    _exact(observation, "transitions", TRANSITIONS, "execution_observation")
    _exact(observation, "frames", FRAMES, "execution_observation")

    identity_result = identity.validate_terminal_artifact_identity(
        _mapping(value.get("terminal_artifact_identity"), "terminal_artifact_identity"),
        plan.audited,
    )
    return {
        "schema": RECEIPT_SCHEMA,
        "status": "terminal_execution_verified_diagnostic_only",
        "seed": plan.seed,
        "plan_digest": plan.plan_digest,
        "real_popen_wait_proof": True,
        "independent_hdf5_validator": True,
        "terminal_artifact_identity": True,
        "trusted_for_formal_credit": False,
        "identity_result": identity_result,
        **ZERO_CREDIT,
    }


def _unique_nonces(nonces: Mapping[int, str] | None) -> dict[int, str]:
    selected: dict[int, str] = {}
    for seed in SEEDS:
        value = (nonces or {}).get(seed, secrets.token_hex(16))
        try:
            selected[seed] = identity._validate_nonce(value, f"nonce.seed{seed}")
        except identity.IdentityError as error:
            raise BridgeError(str(error)) from error
    if len(set(selected.values())) != len(SEEDS):
        _fail("per-seed nonces must be unique")
    return selected


def _empty_side_effects() -> dict[str, Any]:
    return {
        "runtime_started": False,
        "processes_started": 0,
        "processes_stopped": 0,
        "processes_restarted": 0,
        "popen_called": False,
        "wait_observed": False,
        "validator_started": False,
        "queue_submissions": 0,
        "registry_writes": 0,
        "ledger_writes": 0,
        "denominator_writes": 0,
        "gate_writes": 0,
        "completion_writes": 0,
        "synthetic_receipts_minted": 0,
    }


def _empty_input_boundary() -> dict[str, Any]:
    return {
        "bounded_manifest_json_opened": False,
        "bounded_training_json_opened": False,
        "checkpoint_metadata_stat_only": True,
        "checkpoint_content_opened": False,
        "evaluation_content_opened": False,
        "trajectory_hdf5_opened": False,
        "hdf5_validator_content_opened_by_bridge": False,
        "runtime_verifier_current_authorization": False,
        "runtime_started": False,
        "queue_submissions": 0,
    }


def _row(seed: int) -> dict[str, Any]:
    return {
        "seed": seed,
        "status": "blocked_fail_closed",
        "source_bound": False,
        "run_id": identity._expected_run_id(seed),
        "process_proof": None,
        "hdf5_validator": None,
        "terminal_artifact_identity": None,
        "launch_allowed": False,
        "blocked_reasons": [],
    }


def build_report(
    root: Path | str = LAB_ROOT,
    *,
    manifest: Path | str = DEFAULT_MANIFEST,
    training_receipts: Mapping[int, Path | str] | None = None,
    checkpoints: Mapping[int, Path | str] | None = None,
    nonces: Mapping[int, str] | None = None,
    gpu_indices: Mapping[int, int] | None = None,
    output_root: Path | str = "/tmp",
    gpu_rows: Mapping[int, Mapping[str, Any]] | None = None,
    probe_errors: Sequence[str] = (),
    cpu_count: int | None = None,
    load_1m: float | None = None,
    tmp_free_bytes: int | None = None,
    root_free_bytes: int | None = None,
    execution_requested: bool = False,
    observed_at_utc: str | None = None,
) -> dict[str, Any]:
    root_path = Path(os.path.abspath(os.fspath(root)))
    receipts = dict(training_receipts or DEFAULT_RECEIPTS)
    checkpoint_paths = dict(checkpoints or DEFAULT_CHECKPOINTS)
    if set(receipts) != set(SEEDS) or set(checkpoint_paths) != set(SEEDS):
        _fail(f"training_receipts and checkpoints must cover exactly {SEEDS}")
    selected_gpus = {
        seed: int((gpu_indices or DEFAULT_GPU_INDICES).get(seed, DEFAULT_GPU_INDICES[seed]))
        for seed in SEEDS
    }
    if len(set(selected_gpus.values())) != len(SEEDS):
        _fail("per-seed GPU assignments must be unique")
    selected_nonces = _unique_nonces(nonces)
    review = _review_contracts()
    rows: list[dict[str, Any]] = []
    plans: list[BridgePlan] = []
    for seed in SEEDS:
        row = _row(seed)
        gpu = selected_gpus[seed]
        try:
            admission = identity.probe_resource_admission(
                gpu,
                gpu_rows=gpu_rows,
                probe_errors=probe_errors,
                cpu_count=cpu_count,
                load_1m=load_1m,
                tmp_free_bytes=tmp_free_bytes,
                root_free_bytes=root_free_bytes,
            )
            plan = build_bridge_plan(
                root_path,
                seed=seed,
                manifest=manifest,
                training_receipt=receipts[seed],
                checkpoint=checkpoint_paths[seed],
                nonce=selected_nonces[seed],
                output_namespace=Path(output_root)
                / f"f3-graph-residual500-hidden16-currentmanifest-seed{seed}-full835-nonce{selected_nonces[seed]}",
                gpu_index=gpu,
                admission=admission,
            )
            plans.append(plan)
            row.update(
                {
                    "source_bound": True,
                    "run_id": plan.audited.base.run_id,
                    "manifest_sha256": plan.audited.base.manifest_binding["canonical_sha256"],
                    "training_receipt_sha256": plan.audited.base.training_binding["sha256"],
                    "checkpoint": dict(plan.audited.base.checkpoint),
                    "namespace": str(plan.namespace),
                    "namespace_nonce": plan.nonce,
                    "command": list(plan.audited.base.command),
                    "command_sha256": plan.audited.base.command_sha256,
                    "plan_digest": plan.plan_digest,
                    "gpu_index": gpu,
                    "resource_admission": dict(plan.audited.admission),
                    "execution_boundary": build_execution_boundary(
                        plan, execution_requested=execution_requested
                    ),
                    "blocked_reasons": build_execution_boundary(
                        plan, execution_requested=execution_requested
                    )["blocked_reasons"],
                }
            )
        except (BridgeError, identity.IdentityError, launcher.LauncherError, OSError, ValueError) as error:
            row["blocked_reasons"] = [
                str(error),
                f"{EXECUTION_CAPABILITY_SCHEMA} is not implemented/admitted",
                "independent HDF5 validator producer capability is not admitted",
            ]
            row["execution_boundary"] = _blocked_boundary(
                execution_requested=execution_requested,
                blocked=row["blocked_reasons"],
            )
        rows.append(row)

    global_reasons = {
        f"{EXECUTION_CAPABILITY_SCHEMA} is not implemented/admitted",
        "independent HDF5 validator producer capability is not admitted",
        "no evaluator was started and no terminal artifact receipt was minted",
        "real Popen/wait proof is required before terminal identity can be accepted",
        "835 transitions / 836 frames are a required terminal contract, not a progress signal",
    }
    for row in rows:
        global_reasons.update(row.get("blocked_reasons", []))
    observed = observed_at_utc or datetime.now(timezone.utc).isoformat()
    return {
        "schema": REPORT_SCHEMA,
        "report_id": REPORT_ID,
        "observed_at_utc": observed,
        "status": "blocked_fail_closed",
        "mode": "dry_run" if not execution_requested else "execute_request_rejected",
        "dry_run": True,
        "execution_requested": bool(execution_requested),
        "source_bound": len(plans) == len(SEEDS),
        "terminal_source_bound": False,
        "launch_allowed": False,
        "terminal_producer_admitted": False,
        "independent_hdf5_validator_admitted": False,
        "process_proofs_verified": 0,
        "process_proofs_expected": len(SEEDS),
        "hdf5_validators_verified": 0,
        "hdf5_validators_expected": len(SEEDS),
        "terminal_artifacts_verified": 0,
        "terminal_artifacts_expected": len(SEEDS),
        "expected_contract": {
            "model_kind": MODEL,
            "hidden": HIDDEN,
            "updates": UPDATES,
            "case_id": CASE_ID,
            "split": SPLIT,
            "transitions": TRANSITIONS,
            "frames": FRAMES,
            "seeds": list(SEEDS),
            "fresh_32_hex_nonce": True,
            "current_manifest_required": True,
            "training_receipt_and_checkpoint_required": True,
            "exact_command_required": True,
            "real_popen_wait_proof_required": True,
            "independent_hdf5_validator_required": True,
            "diagnostic_only": True,
            "zero_credit_only": True,
        },
        "contract_review": review,
        "seed_rows": rows,
        "blocked_reasons": sorted(global_reasons),
        "input_boundary": {
            **_empty_input_boundary(),
            "bounded_manifest_json_opened": bool(plans),
            "bounded_training_json_opened": bool(plans),
        },
        "side_effects": _empty_side_effects(),
        **ZERO_CREDIT,
    }


def _validate_contract_review(value: Any) -> None:
    review = _mapping(value, "report.contract_review")
    for name in ("launcher", "terminal_artifact_identity", "terminal_runtime_verifier", "current_bridge"):
        _mapping(review.get(name), f"report.contract_review.{name}")
    _exact(review["launcher"], "execute_capability_admitted", False, "report.contract_review.launcher")
    _exact(review["launcher"], "default_launch_allowed", False, "report.contract_review.launcher")
    _exact(review["terminal_artifact_identity"], "execute_capability_admitted", False, "report.contract_review.terminal_artifact_identity")
    _exact(review["terminal_artifact_identity"], "default_launch_allowed", False, "report.contract_review.terminal_artifact_identity")
    _exact(review["terminal_runtime_verifier"], "shared_identity_constants_match", True, "report.contract_review.terminal_runtime_verifier")
    _exact(review["terminal_runtime_verifier"], "direct_current_manifest_admission", False, "report.contract_review.terminal_runtime_verifier")
    _exact(review["terminal_runtime_verifier"], "used_for_current_execution_authorization", False, "report.contract_review.terminal_runtime_verifier")
    _exact(review["current_bridge"], "terminal_producer_admitted", False, "report.contract_review.current_bridge")
    _exact(review["current_bridge"], "independent_hdf5_validator_admitted", False, "report.contract_review.current_bridge")


def _validate_boundary(value: Any, name: str) -> None:
    boundary = _mapping(value, name)
    _unknown(boundary, _BOUNDARY_KEYS, name)
    _exact(boundary, "schema", OBSERVATION_SCHEMA, name)
    _bool(boundary.get("execution_requested"), f"{name}.execution_requested")
    for key in (
        "launch_allowed",
        "terminal_producer_admitted",
        "independent_hdf5_validator_admitted",
        "popen_allowed",
        "popen_called",
        "wait_observed",
        "validator_started",
        "execution_attempted",
    ):
        _exact(boundary, key, False, name)
    _zero_credit(boundary, name)
    if not isinstance(boundary.get("blocked_reasons"), list) or not boundary["blocked_reasons"]:
        _fail(f"{name}.blocked_reasons must be non-empty")


def validate_report(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        value = _mapping(report, "report")
        _unknown(value, _REPORT_KEYS, "report")
        _exact(value, "schema", REPORT_SCHEMA, "report")
        _exact(value, "report_id", REPORT_ID, "report")
        _exact(value, "status", "blocked_fail_closed", "report")
        _exact(value, "dry_run", True, "report")
        _bool(value.get("execution_requested"), "report.execution_requested")
        _bool(value.get("source_bound"), "report.source_bound")
        _exact(value, "terminal_source_bound", False, "report")
        for key in (
            "launch_allowed",
            "terminal_producer_admitted",
            "independent_hdf5_validator_admitted",
        ):
            _exact(value, key, False, "report")
        for key in (
            "process_proofs_verified",
            "hdf5_validators_verified",
            "terminal_artifacts_verified",
        ):
            _exact(value, key, 0, "report")
        for key in (
            "process_proofs_expected",
            "hdf5_validators_expected",
            "terminal_artifacts_expected",
        ):
            _exact(value, key, len(SEEDS), "report")
        _zero_credit(value, "report")
        expected = _mapping(value.get("expected_contract"), "report.expected_contract")
        for key, expected_value in {
            "model_kind": MODEL,
            "hidden": HIDDEN,
            "updates": UPDATES,
            "case_id": CASE_ID,
            "split": SPLIT,
            "transitions": TRANSITIONS,
            "frames": FRAMES,
            "seeds": list(SEEDS),
            "fresh_32_hex_nonce": True,
            "current_manifest_required": True,
            "training_receipt_and_checkpoint_required": True,
            "exact_command_required": True,
            "real_popen_wait_proof_required": True,
            "independent_hdf5_validator_required": True,
            "diagnostic_only": True,
            "zero_credit_only": True,
        }.items():
            _exact(expected, key, expected_value, "report.expected_contract")
        _validate_contract_review(value.get("contract_review"))
        rows = value.get("seed_rows")
        if not isinstance(rows, list) or len(rows) != len(SEEDS):
            _fail("report.seed_rows must contain exactly three rows")
        if [row.get("seed") for row in rows if isinstance(row, Mapping)] != list(SEEDS):
            _fail("report.seed_rows must be ordered as 17, 29, 43")
        for row in rows:
            item = _mapping(row, "report.seed_rows row")
            _unknown(item, _ROW_KEYS, "report.seed_rows row")
            _exact(item, "status", "blocked_fail_closed", "report.seed_rows row")
            _bool(item.get("source_bound"), "report.seed_rows row.source_bound")
            _exact(item, "launch_allowed", False, "report.seed_rows row")
            _exact(item, "process_proof", None, "report.seed_rows row")
            _exact(item, "hdf5_validator", None, "report.seed_rows row")
            _exact(item, "terminal_artifact_identity", None, "report.seed_rows row")
            _validate_boundary(item.get("execution_boundary"), "report.seed_rows row.execution_boundary")
            if not isinstance(item.get("blocked_reasons"), list) or not item["blocked_reasons"]:
                _fail("blocked seed row must include a blocker")
            if item["source_bound"]:
                _mapping(item.get("checkpoint"), "report.seed_rows row.checkpoint")
                _string(item.get("namespace"), "report.seed_rows row.namespace")
                _string(item.get("namespace_nonce"), "report.seed_rows row.namespace_nonce")
                _sha(item.get("manifest_sha256"), "report.seed_rows row.manifest_sha256")
                _sha(item.get("training_receipt_sha256"), "report.seed_rows row.training_receipt_sha256")
                _sha(item.get("command_sha256"), "report.seed_rows row.command_sha256")
                _sha(item.get("plan_digest"), "report.seed_rows row.plan_digest")
        input_boundary = _mapping(value.get("input_boundary"), "report.input_boundary")
        for key, expected_value in _empty_input_boundary().items():
            if key in {"bounded_manifest_json_opened", "bounded_training_json_opened"}:
                continue
            _exact(input_boundary, key, expected_value, "report.input_boundary")
        if input_boundary.get("bounded_manifest_json_opened") is not bool(value.get("source_bound")):
            _fail("report.input_boundary manifest/source binding disagrees with source_bound")
        side_effects = _mapping(value.get("side_effects"), "report.side_effects")
        for key, expected_value in _empty_side_effects().items():
            _exact(side_effects, key, expected_value, "report.side_effects")
        if not isinstance(value.get("blocked_reasons"), list) or not value["blocked_reasons"]:
            _fail("report.blocked_reasons must be non-empty")
        _string(value.get("observed_at_utc"), "report.observed_at_utc")
    except (BridgeError, TypeError, KeyError, AttributeError) as error:
        errors.append(str(error))
    return errors


def render_zh_report(report: Mapping[str, Any]) -> str:
    lines = [
        "# F3 graph_residual hidden16 current-manifest terminal execution bridge",
        "",
        f"- status: `{report.get('status')}`",
        f"- mode: `{report.get('mode')}`；dry-run: `{report.get('dry_run')}`",
        f"- source_bound: `{report.get('source_bound')}`；terminal source bound: `{report.get('terminal_source_bound')}`",
        "- launch_allowed: `False`；Popen/wait proof、独立 HDF5 validator、terminal identity：`0/3`",
        "- contract: graph_residual / hidden16 / 500 updates / current manifest / test / 835 transitions / 836 frames",
        "- boundary: training/checkpoint、fresh nonce、exact command、real Popen/wait、独立 HDF5 validator；diagnostic-only、zero-credit",
        "",
        "| seed | GPU | source bound | nonce | status |",
        "|---:|---:|---|---|---|",
    ]
    for row in report.get("seed_rows", []):
        if isinstance(row, Mapping):
            lines.append(
                f"| {row.get('seed')} | {row.get('gpu_index', '')} | `{row.get('source_bound')}` | "
                f"`{row.get('namespace_nonce', '')}` | `{row.get('status')}` |"
            )
    lines.extend(["", "## Blockers", ""])
    lines.extend(f"- {reason}" for reason in report.get("blocked_reasons", []))
    return "\n".join(lines) + "\n"


def _write_new(path: Path, content: str) -> None:
    if path.exists() or path.is_symlink():
        _fail(f"refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _parse_nonces(values: Sequence[str]) -> dict[int, str]:
    result: dict[int, str] = {}
    for raw in values:
        if "=" not in raw:
            _fail("--nonce must use SEED=NONCE")
        seed_text, nonce = raw.split("=", 1)
        try:
            seed = int(seed_text)
        except ValueError as error:
            raise BridgeError("--nonce seed must be an integer") from error
        if seed not in SEEDS or seed in result:
            _fail(f"--nonce seed must be unique and one of {SEEDS}")
        try:
            result[seed] = identity._validate_nonce(nonce, f"nonce.seed{seed}")
        except identity.IdentityError as error:
            raise BridgeError(str(error)) from error
    if set(result) != set(SEEDS):
        _fail(f"--nonce must cover exactly {SEEDS}")
    return result


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument("--execute", action="store_true", help="request execution; current capability rejects it before Popen")
    parser.add_argument("--nonce", action="append", default=[], metavar="SEED=NONCE")
    parser.add_argument("--write-report", type=Path)
    parser.add_argument("--write-zh-report", type=Path)
    parser.add_argument("--verify-report", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.verify_report is not None:
            value = json.loads(args.verify_report.read_text(encoding="utf-8"))
            errors = validate_report(value)
            print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, sort_keys=True))
            return 0 if not errors else 1
        nonces = _parse_nonces(args.nonce) if args.nonce else None
        report = build_report(args.root, nonces=nonces, execution_requested=args.execute)
        if args.write_report is not None:
            _write_new(args.write_report, json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        if args.write_zh_report is not None:
            _write_new(args.write_zh_report, render_zh_report(report))
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 2
    except (BridgeError, identity.IdentityError, launcher.LauncherError, OSError, ValueError) as error:
        print(json.dumps({"status": "blocked_fail_closed", "error": str(error)}, ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
