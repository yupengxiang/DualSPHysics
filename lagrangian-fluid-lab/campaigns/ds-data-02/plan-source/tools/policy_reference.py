"""Pure, no-I/O reference policy for a DATA-ONLY campaign.

This does not validate CFD, files, signatures or execute jobs. Callers must
supply independently verified evidence from the actual data pipeline.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping, Any

PROHIBITED = frozenset({
    "model_training", "model_inference", "checkpoint_loading",
    "hyperparameter_search", "model_ranking", "model_qualification",
})

@dataclass(frozen=True)
class Decision:
    allowed: bool
    reasons: tuple[str, ...]


def admit_native_case(case: Mapping[str, Any], receipt: Mapping[str, Any],
                      resources: Mapping[str, Any]) -> Decision:
    """One recipe/scope only: no other-family, learner or external-test gate."""
    errors: list[str] = []
    if case.get("task_kind") != "production":
        errors.append("task_not_native_data_production")
    if case.get("task_kind") in PROHIBITED:
        errors.append("learner_work_out_of_scope")
    for field in ("family_id", "recipe_id", "qualified_scope_id"):
        if not case.get(field) or case.get(field) != receipt.get(field):
            errors.append(f"scope_mismatch:{field}")
    if receipt.get("role") == "canary":
        errors.append("canary_is_not_numerical_reference")
    if receipt.get("numerical_reference_status") != "qualified":
        errors.append("numerical_reference_missing")
    if receipt.get("data_semantics") != "native_numerical_trajectory":
        errors.append("unrecognized_reference_semantics")
    for field in ("integrity_passed", "within_verified_domain", "full_event_window",
                  "split_lineage_passed", "active_inputs_verified"):
        if case.get(field) is not True:
            errors.append(f"case_gate:{field}")
    if case.get("target_view") == "core_3d" and case.get("solver_dimension") != 3:
        errors.append("not_verified_solver_3d")
    if case.get("target_view") == "core_3d" and case.get("lifecycle") not in {"closed", "periodic"}:
        errors.append("open_or_adaptive_requires_separate_view")
    if case.get("lifecycle") not in {"closed", "open", "periodic", "adaptive"}:
        errors.append("unknown_lifecycle")
    if case.get("lifecycle") != "closed" and case.get("lifecycle_accounting_passed") is not True:
        errors.append("lifecycle_accounting_missing")
    if not case.get("physical_case_id") or not case.get("lineage_group_id"):
        errors.append("physical_identity_missing")
    for field in ("owner_adoption_valid", "within_budget", "within_deadline", "resource_lease_valid"):
        if resources.get(field) is not True:
            errors.append(f"resource_gate:{field}")
    return Decision(not errors, tuple(errors))


def can_finish(*, product_complete: bool, ready_task_count: int,
               required_branches_have_terminal_evidence: bool,
               hard_resource_stop: bool = False, owner_stop: bool = False) -> bool:
    if ready_task_count < 0:
        raise ValueError("negative ready_task_count")
    if owner_stop or hard_resource_stop:
        return True  # caller must mark partial, not scientific success
    if product_complete:
        return True
    return ready_task_count == 0 and required_branches_have_terminal_evidence
