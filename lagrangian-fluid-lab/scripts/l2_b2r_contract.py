#!/usr/bin/env python3
"""Independent B2R preparation contract.

The historical :mod:`l2_b2_learning` script only registers a candidate-only
three-seed result.  This module describes the new L2-R study without changing
the shared resume state or pretending that R2 is already accepted.

The default preparation result is intentionally ``waiting_for_R2``.  A caller
must supply explicit R2 evidence containing the current F3 contract, actual
oracle runs, and the legacy-reuse boundary before an execution guard can open.
Even then this module only prepares a study; it never starts training.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

try:
    from scripts.l2_b2r_model import MODEL_SCHEMA, graph_model_contract
except ModuleNotFoundError:  # direct ``python scripts/l2_b2r_prepare.py``
    from l2_b2r_model import MODEL_SCHEMA, graph_model_contract


LAB = Path(__file__).resolve().parents[1]
DEFAULT_CASE_REGISTRY = LAB / "campaigns/l2-multifamily/evidence/f3-canonical-manifest.json"
DEFAULT_CURRENT_F3_CONTRACT = LAB / "campaigns/l2-multifamily/resume-c6b28c8/current-f3-contract.json"
HISTORICAL_B2_SCRIPT = "scripts/l2_b2_learning.py"
HISTORICAL_B2_REPORT = "campaigns/l2-multifamily/reports/b2-learning-baseline.json"
CONTRACT_SCHEMA = "l2r.b2r.preparation_contract.v1"
CURRENT_F3_CONTRACT_SCHEMA = "l2r.r2.current_f3_contract.v1"
ATTEMPT_SCHEMA = "l2r.b2r.training_attempt.v1"
DENOMINATOR_SCHEMA = "l2r.b2r.failure_denominator.v1"
R2_REQUIRED_OUTPUTS = (
    "current_f3_contract",
    "actual_oracle_runs",
    "legacy_reuse_manifest",
)
ROUTES = ("raw", "hybrid")
SEEDS = (17, 29, 43)
DEFAULT_NODE_FEATURE_NAMES = (
    "mass_over_reference",
    "density_over_reference",
    "pressure_over_reference",
    "boundary_distance_over_length",
    "boundary_normal_x",
    "boundary_normal_y",
    "boundary_normal_z",
    "boundary_presence",
)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class B2RContractError(ValueError):
    """Raised when a B2R preparation or evidence contract is malformed."""


class B2RWaitingForR2(RuntimeError):
    """Raised when an execution-only operation is attempted before R2."""

    status = "waiting_for_R2"


@dataclass(frozen=True)
class R2Gate:
    status: str = "waiting_for_R2"
    launch_allowed: bool = False
    reason: str = "R2 evidence was not supplied to the independent B2R entrypoint"
    required_outputs: tuple[str, ...] = R2_REQUIRED_OUTPUTS
    source: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "launch_allowed": self.launch_allowed,
            "reason": self.reason,
            "required_outputs": list(self.required_outputs),
            "source": self.source,
        }


@dataclass(frozen=True)
class StudySpec:
    """Frozen design facts for the six logical B2R runs."""

    study_id: str = "L2R_B2R_GRAPH_CONTROLLED_V1"
    routes: tuple[str, ...] = ROUTES
    seeds: tuple[int, ...] = SEEDS
    evaluation_case_ids: tuple[str, ...] = ()
    evaluation_case_registry: str = "campaigns/l2-multifamily/evidence/f3-canonical-manifest.json"
    node_feature_names: tuple[str, ...] = DEFAULT_NODE_FEATURE_NAMES
    edge_feature_names: tuple[str, ...] = (
        "relative_position_x",
        "relative_position_y",
        "relative_position_z",
        "relative_velocity_x",
        "relative_velocity_y",
        "relative_velocity_z",
        "distance",
    )
    hidden: int = 64
    message_steps: int = 2
    training_steps_registered: int = 0
    r2_gate: R2Gate = field(default_factory=R2Gate)
    r0_verified: bool = False

    def __post_init__(self) -> None:
        if not self.study_id or not _SAFE_ID.fullmatch(self.study_id):
            raise B2RContractError("study_id must be a safe nonempty identifier")
        if tuple(self.routes) != ROUTES or tuple(self.seeds) != SEEDS:
            raise B2RContractError("B2R requires exactly raw/hybrid routes and seeds 17,29,43")
        if not self.node_feature_names or len(set(self.node_feature_names)) != len(self.node_feature_names):
            raise B2RContractError("node feature names must be unique and nonempty")
        if len(self.edge_feature_names) != 7 or len(set(self.edge_feature_names)) != 7:
            raise B2RContractError("the declared graph edge contract must have seven unique features")
        if self.hidden < 4 or self.message_steps < 1:
            raise B2RContractError("invalid graph architecture dimensions")
        if self.training_steps_registered != 0:
            raise B2RContractError("preparation must not register an unreviewed training step budget")
        if any(not isinstance(case_id, str) or not _SAFE_ID.fullmatch(case_id) for case_id in self.evaluation_case_ids):
            raise B2RContractError("evaluation case IDs must be safe identifiers")
        if len(set(self.evaluation_case_ids)) != len(self.evaluation_case_ids):
            raise B2RContractError("evaluation case IDs must be unique")

    @property
    def logical_runs(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            {
                "logical_run_id": f"{self.study_id}_{route}_seed{seed}",
                "route": route,
                "seed": seed,
                "model_family": "current_state_particle_graph_message_passing",
                "evaluation_case_ids": list(self.evaluation_case_ids),
                "status": "not_started",
            }
            for route in self.routes
            for seed in self.seeds
        )


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _relative_to_lab(path: Path) -> str:
    try:
        return path.resolve().relative_to(LAB.resolve()).as_posix()
    except ValueError as error:
        raise B2RContractError(f"B2R source must remain inside the lab: {path}") from error


def _resolve_lab_path(path: str | Path) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = LAB / candidate
    candidate = candidate.resolve()
    _relative_to_lab(candidate)
    return candidate


def _source_ref(path: str | Path) -> dict[str, Any]:
    resolved = _resolve_lab_path(path)
    return {
        "path": _relative_to_lab(resolved),
        "exists": resolved.is_file(),
        "sha256": sha256_file(resolved) if resolved.is_file() else None,
        "bytes": resolved.stat().st_size if resolved.is_file() else None,
    }


def validate_current_f3_contract(contract: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the current F3 data/target contract bound to B2R.

    B2R is a new graph architecture, so it does not claim to use the legacy
    43-feature checkpoint.  It must nevertheless be attached to the current
    F3 contract that defines the registered data, causal boundary and target
    update.  The current model checkpoint may still be absent; that is an R2
    finding, not permission to silently fall back to the historical model.
    """

    if not isinstance(contract, Mapping) or contract.get("schema") != CURRENT_F3_CONTRACT_SCHEMA:
        raise B2RContractError("B2R requires the current F3 contract schema")
    data_contract = contract.get("data_contract")
    if not isinstance(data_contract, Mapping):
        raise B2RContractError("current F3 contract has no data_contract block")
    if data_contract.get("feature_width") != 48 or data_contract.get("recorded_feature_width") != 48:
        raise B2RContractError("current F3 contract must bind the 48-feature input width")
    if data_contract.get("future_fluid_state_allowed") is not False:
        raise B2RContractError("current F3 contract permits future fluid state")
    if data_contract.get("future_free_body_state_allowed") is not False:
        raise B2RContractError("current F3 contract permits future free-body state")
    target = str(data_contract.get("target_convention", ""))
    if "next" not in target.lower() or "current" not in target.lower():
        raise B2RContractError("current F3 target convention is not current-to-next displacement")
    identity = str(data_contract.get("identity_convention", ""))
    if "native" not in identity.lower() or "id" not in identity.lower():
        raise B2RContractError("current F3 identity convention is not native-ID based")
    recipe = contract.get("recipe")
    if not isinstance(recipe, Mapping) or not recipe.get("recipe_id"):
        raise B2RContractError("current F3 recipe binding is missing")
    return {
        "valid": True,
        "schema": CURRENT_F3_CONTRACT_SCHEMA,
        "feature_width": 48,
        "recipe_id": recipe["recipe_id"],
        "qualification_claim": bool(contract.get("qualification", {}).get("current_model_qualified", False)),
    }


def load_current_f3_contract(path: str | Path = DEFAULT_CURRENT_F3_CONTRACT) -> tuple[Path, dict[str, Any]]:
    """Load and validate the current F3 contract without touching shared state."""

    resolved = _resolve_lab_path(path)
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    try:
        payload = json.loads(resolved.read_text())
    except json.JSONDecodeError as error:
        raise B2RContractError(f"invalid current F3 contract JSON: {resolved}") from error
    validate_current_f3_contract(payload)
    return resolved, payload


def load_evaluation_case_registry(
    path: str | Path = DEFAULT_CASE_REGISTRY,
    *,
    evaluation_splits: Iterable[str] = ("validation", "test"),
) -> dict[str, Any]:
    """Read the current F3 case registry without opening trajectory data.

    The denominator is the 16 non-training physical cases (12 test + 4
    validation in the retained manifest).  The IDs are read from the registry,
    never invented by the B2R preparation layer.
    """

    resolved = _resolve_lab_path(path)
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    try:
        payload = json.loads(resolved.read_text())
    except json.JSONDecodeError as error:
        raise B2RContractError(f"invalid case registry JSON: {resolved}") from error
    if payload.get("schema") != "l2.f3.canonical_manifest.v1":
        raise B2RContractError("B2R requires the canonical F3 case registry schema")
    selected_splits = {str(value) for value in evaluation_splits}
    if not selected_splits:
        raise B2RContractError("at least one evaluation split is required")
    rows = []
    seen_physical: set[str] = set()
    for row in payload.get("cases", []):
        if not isinstance(row, Mapping) or row.get("split") not in selected_splits:
            continue
        case_id = row.get("case_id")
        physical_case_id = row.get("physical_case_id")
        lineage_group_id = row.get("lineage_group_id")
        if (
            not isinstance(case_id, str)
            or not _SAFE_ID.fullmatch(case_id)
            or not isinstance(physical_case_id, str)
            or not _SAFE_ID.fullmatch(physical_case_id)
            or not isinstance(lineage_group_id, str)
            or not lineage_group_id
        ):
            raise B2RContractError("evaluation registry row lacks safe case/physical/lineage IDs")
        if physical_case_id in seen_physical:
            raise B2RContractError("evaluation registry repeats a physical case")
        seen_physical.add(physical_case_id)
        rows.append(
            {
                "case_id": case_id,
                "physical_case_id": physical_case_id,
                "lineage_group_id": lineage_group_id,
                "paired_background_id": row.get("paired_background_id"),
                "family": row.get("family"),
                "split": row.get("split"),
                "evaluation_role": row.get("evaluation_role"),
                "recipe_id": row.get("recipe_id"),
            }
        )
    if not rows:
        raise B2RContractError("evaluation registry selected no physical cases")
    rows.sort(key=lambda row: row["physical_case_id"])
    return {
        "schema": "l2r.b2r.evaluation_case_registry.v1",
        "source": _source_ref(resolved),
        "selection": {"splits": sorted(selected_splits), "same_lineage_not_cross_split": True},
        "case_count": len(rows),
        "physical_case_ids": [row["physical_case_id"] for row in rows],
        "cases": rows,
    }


def evaluate_r2_dependency(evidence: Mapping[str, Any] | None = None) -> R2Gate:
    """Evaluate explicit R2 evidence; absent evidence always stays waiting.

    This function does not inspect or update ``resume-c6b28c8/state.json``.
    That separation is intentional: B2R preparation cannot silently promote a
    shared scheduler label or the historical B2 report.
    """

    if evidence is None:
        return R2Gate()
    if not isinstance(evidence, Mapping):
        return R2Gate(reason="supplied R2 evidence is not a mapping")
    acceptance = evidence.get("acceptance")
    if evidence.get("schema") != "l2r.r2.f3_contract.v1" or not isinstance(acceptance, Mapping):
        return R2Gate(reason="R2 evidence schema or acceptance block is missing")
    missing = [key for key in R2_REQUIRED_OUTPUTS if not bool(acceptance.get(_r2_acceptance_key(key), False))]
    if missing:
        return R2Gate(reason="R2 acceptance is incomplete: " + ", ".join(missing))
    if evidence.get("status") not in {"complete", "complete_with_findings"}:
        return R2Gate(reason="R2 evidence is not terminal")
    source = {
        "schema": evidence.get("schema"),
        "status": evidence.get("status"),
        "report_sha256": evidence.get("report_sha256"),
    }
    return R2Gate(
        status="satisfied",
        launch_allowed=True,
        reason="explicit R2 contract/oracle/legacy-boundary evidence supplied",
        source=source,
    )


def _r2_acceptance_key(output: str) -> str:
    return {
        "current_f3_contract": "current_f3_contract_recorded",
        "actual_oracle_runs": "actual_oracle_runs_recorded",
        "legacy_reuse_manifest": "legacy_reuse_boundary_explicit",
    }[output]


def build_study_spec(
    *,
    registry_path: str | Path = DEFAULT_CASE_REGISTRY,
    current_f3_contract_path: str | Path = DEFAULT_CURRENT_F3_CONTRACT,
    r2_evidence: Mapping[str, Any] | None = None,
    r0_verified: bool = False,
) -> tuple[StudySpec, dict[str, Any]]:
    """Prepare the controlled study and its independent denominator manifest."""

    registry = load_evaluation_case_registry(registry_path)
    current_f3_path, current_f3_contract = load_current_f3_contract(current_f3_contract_path)
    gate = evaluate_r2_dependency(r2_evidence)
    spec = StudySpec(
        evaluation_case_ids=tuple(registry["physical_case_ids"]),
        evaluation_case_registry=registry["source"]["path"],
        r2_gate=gate,
        r0_verified=bool(r0_verified),
    )
    launch_allowed = bool(r0_verified and gate.launch_allowed)
    # R2 is the explicit user-controlled gate.  If R2 evidence is present but
    # the independent R0 check is not, preparation is still non-executable but
    # should not falsely describe R2 as missing.
    status = "waiting_for_R2" if not gate.launch_allowed else "prepared_not_launched"
    manifest = {
        "schema": CONTRACT_SCHEMA,
        "study_id": spec.study_id,
        "status": status,
        "execution_status": status,
        "launch_allowed": launch_allowed,
        "created_by": "scripts/l2_b2r_prepare.py",
        "dependencies": {
            "R0": {
                "required": True,
                "status": "verified_for_design" if r0_verified else "not_verified_by_B2R",
                "shared_resume_mutation": False,
            },
            "R2": {
                "required": True,
                **gate.as_dict(),
                "shared_resume_mutation": False,
            },
        },
        "historical_baseline_boundary": {
            "script": HISTORICAL_B2_SCRIPT,
            "report": HISTORICAL_B2_REPORT,
            "historical_registration_is_complete": True,
            "new_graph_study_substituted": False,
            "new_training_attempts": 0,
            "can_satisfy_B2R": False,
        },
        "model_contract": {
            **graph_model_contract(
            node_features=len(spec.node_feature_names),
            edge_features=len(spec.edge_feature_names),
            hidden=spec.hidden,
            message_steps=spec.message_steps,
            ),
            "current_f3_contract_binding": {
                "schema": CURRENT_F3_CONTRACT_SCHEMA,
                "source": _source_ref(current_f3_path),
                "feature_width": current_f3_contract["data_contract"]["feature_width"],
                "target_convention": current_f3_contract["data_contract"]["target_convention"],
                "identity_convention": current_f3_contract["data_contract"]["identity_convention"],
                "legacy_checkpoint_reuse": False,
            },
        },
        "study_design": {
            "routes": [
                {
                    "route": "raw",
                    "same_graph_trunk_as": "hybrid",
                    "target": "direct next displacement",
                    "known_operator": None,
                    "posthoc_wall_projection": False,
                    "output_clipping": False,
                },
                {
                    "route": "hybrid",
                    "same_graph_trunk_as": "raw",
                    "target": "acceleration residual around known-control displacement prior",
                    "known_operator": "v*dt + 0.5*a_control*dt^2",
                    "allowed_known_inputs": ["current control", "current geometry/material features"],
                    "posthoc_wall_projection": False,
                    "output_clipping": False,
                    "required_cost_metrics": [
                        "residual_displacement_l2",
                        "residual_trigger_count",
                        "prior_and_residual_cost",
                    ],
                },
            ],
            "seeds": list(spec.seeds),
            "logical_run_count": len(spec.logical_runs),
            "logical_runs": list(spec.logical_runs),
            "no_training_started_by_preparation": True,
        },
        "data_contract": {
            "source_role": "registered F3 development data; no hidden test",
            "current_f3_contract": {
                "source": _source_ref(current_f3_path),
                "schema": CURRENT_F3_CONTRACT_SCHEMA,
                "feature_width": current_f3_contract["data_contract"]["feature_width"],
                "recipe_id": current_f3_contract["recipe"]["recipe_id"],
            },
            "evaluation_case_registry": registry,
            "evaluation_denominator_unit": "unique physical_case_id",
            "lineage_rule": "resolution/restart/window views stay within lineage and do not create new physical cases",
            "future_reference_state_allowed": False,
        },
        "attempt_contract": {
            "schema": ATTEMPT_SCHEMA,
            "required_status_layers": [
                "training_completed",
                "worker_exit_status",
                "evaluation_completed",
                "model_physical_pass",
            ],
            "failed_and_retried_attempts_in_manifest": True,
            "retries_do_not_duplicate_physical_case_denominator": True,
        },
        "failure_denominator_contract": {
            "schema": DENOMINATOR_SCHEMA,
            "planned_logical_run_count": len(spec.logical_runs),
            "planned_evaluation_case_count": registry["case_count"],
            "all_outcomes_required": True,
            "not_started_is_failure_denominator": True,
            "worker_or_evaluation_failure_is_not_model_physical_pass": True,
            "physical_case_unit": "physical_case_id",
        },
        "acceptance": {
            "new_graph_model_contract_written": True,
            "raw_hybrid_controlled_matrix_declared": True,
            "new_training_attempts_executed": False,
            "full_failure_denominator_ready_for_records": True,
            "r2_dependency_satisfied": gate.launch_allowed,
            "waiting_for_R2": not gate.launch_allowed,
            "B2R_terminal": False,
        },
    }
    return spec, manifest


def assert_execution_allowed(spec: StudySpec) -> None:
    """Guard a future runner; this function never starts a process."""

    if not spec.r0_verified:
        raise B2RWaitingForR2(
            "B2R execution is not enabled: waiting_for_R2 gate remains closed until R0 is independently verified"
        )
    if not spec.r2_gate.launch_allowed:
        raise B2RWaitingForR2("B2R execution is waiting_for_R2: current contract/oracle evidence is not supplied")


def validate_preparation_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Validate that preparation cannot be mistaken for a completed study."""

    if manifest.get("schema") != CONTRACT_SCHEMA:
        raise B2RContractError("unexpected B2R preparation schema")
    if manifest.get("status") not in {"waiting_for_R2", "prepared_not_launched"}:
        raise B2RContractError("preparation status must not be terminal")
    if manifest.get("acceptance", {}).get("B2R_terminal") is not False:
        raise B2RContractError("B2R preparation must explicitly remain non-terminal")
    if manifest.get("historical_baseline_boundary", {}).get("can_satisfy_B2R") is not False:
        raise B2RContractError("historical B2 report cannot satisfy B2R")
    current_f3 = manifest.get("data_contract", {}).get("current_f3_contract", {})
    if current_f3.get("schema") != CURRENT_F3_CONTRACT_SCHEMA:
        raise B2RContractError("B2R preparation is not bound to the current F3 contract")
    if current_f3.get("feature_width") != 48 or not isinstance(current_f3.get("source"), Mapping):
        raise B2RContractError("B2R current F3 contract binding is incomplete")
    dependency = manifest.get("dependencies", {}).get("R2", {})
    if manifest.get("status") == "waiting_for_R2" and dependency.get("status") != "waiting_for_R2":
        raise B2RContractError("waiting_for_R2 status must be backed by the R2 dependency")
    if manifest.get("launch_allowed") and manifest.get("status") != "prepared_not_launched":
        raise B2RContractError("launch_allowed preparation must still be non-terminal")
    return {"valid": True, "status": manifest.get("status"), "launch_allowed": bool(manifest.get("launch_allowed"))}
