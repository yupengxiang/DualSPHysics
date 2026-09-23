#!/usr/bin/env python3
"""Reconcile the user-selected F8 route with its current zero-credit state.

The v2 frontier predates the accepted F8 family ruling and the R008 scope
design.  This version records F8 as the selected third-family candidate while
keeping T1 admission, solver execution, and qualification credit closed until
the separate scientific gates are satisfied.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import core_third_t1_frontier_audit_v2 as _legacy


LAB = Path(__file__).resolve().parents[1]
OUTPUT = LAB / "campaigns/core-v1/evidence/core-third-t1-frontier-audit-20260923-v3.json"
F8 = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008")
RULING = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/root-scope-ruling-v1/receipt.json")
STATUS_UPDATE = Path("reports/CORE-CONTINUATION-STATUS-2026-09-23-UPDATE-02.zh-CN.md")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def bind(relative: Path, role: str) -> dict[str, Any]:
    path = LAB / relative
    return {"path": str(relative), "sha256": sha256(path),
            "bytes": path.stat().st_size, "role": role}


def _read(relative: Path) -> dict[str, Any]:
    value = json.loads((LAB / relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {relative}")
    return value


def _verify_reference(reference: dict[str, Any], expected_path: Path) -> None:
    if reference.get("path") != str(expected_path):
        raise ValueError(f"unexpected bound path: {reference.get('path')}")
    path = LAB / expected_path
    if (reference.get("bytes") != path.stat().st_size
            or reference.get("sha256") != sha256(path)):
        raise ValueError(f"stale bound file: {expected_path}")


def build_audit() -> dict[str, Any]:
    value = copy.deepcopy(_legacy.build_audit())
    ruling = _read(RULING)
    scope_path = F8 / "t1-scope-design-v1/receipt.json"
    review_path = F8 / "t1-scope-design-review-v1/review.json"
    static_review_path = F8 / "independent-static-review-terra-high-v1/receipt.json"
    resource_path = F8 / "resource-admission-v1/receipt.json"
    request_path = F8 / "cpu-native-preflight-request-v3/request.json"
    authorization_path = F8 / "cpu-native-preflight-authorization-v1/authorization.json"
    scope = _read(scope_path)
    review = _read(review_path)
    static_review = _read(static_review_path)
    resource = _read(resource_path)
    request = _read(request_path)
    authorization = _read(authorization_path)

    if not (
        ruling.get("schema") == "core.cfd.f8.root_scope_ruling.v1"
        and ruling.get("status") == "accepted_as_distinct_mechanism_family_static_review_only"
        and ruling.get("user_ruling", {}).get("inferred") is False
        and ruling.get("scope_effect", {}).get("eligible_for_core_third_family_denominator") is False
        and ruling.get("qualification_credit") == 0
    ):
        raise ValueError("the F8 family ruling is missing or no longer zero-credit")
    scope_id = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008"
    if not (
        scope.get("schema") == "core.cfd.f8.t1_scope_design.v1"
        and scope.get("scope_id") == scope_id
        and scope.get("mechanism") == "fully filled, body-force-driven oscillatory viscous channel; no free surface"
        and scope.get("status") == "static_scope_design_candidate_ready_for_independent_review"
        and scope.get("qualification_credit") == 0
        and scope.get("matrix", {}).get("case_count") == 15
    ):
        raise ValueError("the R008 frozen T1 candidate does not match the accepted F8 route")
    if not (
        review.get("schema") == "core.cfd.f8.r008_t1_scope_design_independent_review.v1"
        and review.get("status") == "static_design_review_passed_execution_readiness_blocked"
        and review.get("qualification", {}).get("T1_numerical") is False
        and review.get("qualification", {}).get("credit") == 0
    ):
        raise ValueError("the R008 design review no longer supports zero-credit pending status")
    if not (
        static_review.get("scope_id") == scope_id
        and static_review.get("status") == "r008_static_design_conditionally_passed_cpu_native_preflight_only"
        and static_review.get("decision_boundary", {}).get("execution_authorized_by_this_review") is False
        and static_review.get("execution_controls", {}).get("qualification_credit") == 0
    ):
        raise ValueError("the R008 independent review boundary changed")
    if not (
        resource.get("schema") == "core.cfd.f8_r008_resource_admission.v1"
        and resource.get("status") == "conditional_ram_cap_cpu_schedule_blocked_no_execution_authority"
        and resource.get("resource_decision", {}).get("solver_invocations") == 0
        and resource.get("resource_decision", {}).get("qualification_credit") == 0
    ):
        raise ValueError("the R008 resource decision changed")
    if not (
        request.get("schema") == "core.cfd.f8.r008_cpu_native_preflight_request.v3"
        and request.get("scope_id") == scope_id
        and request.get("request_only") is True
        and request.get("source_binding_count") == 24
        and request.get("authorization", {}).get("this_request_grants_execution") is False
        and request.get("execution_controls", {}).get("qualification_credit") == 0
    ):
        raise ValueError("the R008 v3 request is not an exact zero-credit request-only artifact")
    if not (
        authorization.get("schema") == "core.cfd.f8.r008_cpu_native_preflight_authorization.v1"
        and authorization.get("scope_id") == scope_id
        and authorization.get("status") == "authorized_for_exactly_one_r008_cpu_native_preflight"
        and authorization.get("qualification_credit") == 0
        and authorization.get("permissions", {}).get("cpu_gencase") is True
        and authorization.get("permissions", {}).get("native_decode") is True
        and authorization.get("permissions", {}).get("solver") is False
        and authorization.get("permissions", {}).get("worker") is False
        and authorization.get("permissions", {}).get("gpu") is False
        and authorization.get("output_namespace", {}).get("must_be_absent_before_start") is True
        and authorization.get("output_namespace", {}).get("reuse_or_retry_allowed") is False
    ):
        raise ValueError("the R008 authorization exceeds the recorded one-shot CPU scope")
    _verify_reference(authorization["request_reference"], request_path)
    _verify_reference(authorization["independent_review_reference"], static_review_path)

    value["schema"] = "core.third_t1.frontier_audit.v3"
    value["status"] = "user_selected_candidate_pending_one_shot_preflight_and_t1_qualification"
    value["decision"] = (
        "advance_user_selected_f8_r008_only_through_authorized_cpu_preflight_after_live_gates; "
        "keep_core_incomplete_and_award_zero_qualification_credit"
    )
    value["decision_source"] = {
        "path": str(RULING),
        "status": ruling["status"],
        "user_statement": ruling["user_ruling"]["statement"],
        "effect": "selects the intended mechanism-family route only; does not grant denominator eligibility, T1 qualification, solver execution, or credit",
        "denominator_eligible_before_t1_qualification": False,
    }
    value["qualification_claim"] = "none"
    value["qualification_credit"] = 0
    value["third_family_established"] = False

    f8 = value["route_decisions"]["F8"]
    f8["historical_r001_status"] = f8.pop("status")
    f8["historical_r001_scope_id"] = f8.get("scope_id")
    f8["historical_r001_admission_granted"] = f8.pop("admission_granted")
    f8["historical_r001_reference_oracle"] = f8.pop("reference_oracle")
    f8["historical_r001_parameter_contract"] = f8.pop("parameter_contract")
    f8["historical_r001_terra_high_review"] = f8.pop("terra_high_review")
    f8["scope_id"] = scope_id
    f8["mechanism"] = scope["mechanism"]
    f8["fresh_definition_present"] = True
    f8["route_selected_by_user"] = True
    f8["t1_scope_design_status"] = scope["status"]
    f8["t1_design_review_status"] = review["status"]
    f8["independent_static_review_status"] = static_review["status"]
    f8["cpu_native_preflight_authorized"] = True
    f8["cpu_native_preflight_status"] = authorization["status"]
    f8["preflight_only_not_solver_or_qualification"] = True
    f8["solver_t1_execution_authorized"] = False
    f8["t1_solver_admission_granted"] = False
    f8["t1_qualification"] = False
    f8["qualification_claim"] = "none"
    f8["qualification_credit"] = 0
    f8["live_gate"] = "recheck immediately before the one-shot preflight; F3 worker absence and load <= CPU affinity are mandatory"
    f8["next_allowed_action"] = (
        "run exactly one authorized CPU GenCase plus at most one native decoder only after every live gate passes; "
        "any solver or T1 matrix requires separate authorization"
    )

    value["execution_controls"].update({
        "gencase_invoked": False,
        "native_decode_invoked": False,
        "solver_invoked": False,
        "worker_started": False,
        "preflight_output_namespace_created_as_of_bound_update": False,
        "qualification_credit": 0,
    })
    value["evidence"].extend([
        bind(RULING, "user-accepted F8 mechanism-family ruling; no T1/denominator eligibility"),
        bind(scope_path, "fresh R008 frozen T1 scope design"),
        bind(review_path, "independent R008 T1 design review"),
        bind(static_review_path, "R008 independent static review; CPU/native preflight only"),
        bind(resource_path, "R008 conditional resource-admission decision"),
        bind(request_path, "R008 v3 request-only CPU/native preflight request"),
        bind(authorization_path, "R008 exact one-shot CPU/native preflight authorization"),
        bind(STATUS_UPDATE, "latest bound status: preflight deferred by live resource gates; no runtime namespace or consumed lock"),
        bind(Path(__file__).resolve().relative_to(LAB), "v3 frontier audit writer"),
    ])
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    result = build_audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(json.dumps({key: result[key] for key in
                      ("schema", "status", "decision", "current_t1_families",
                       "third_family_established", "qualification_credit", "execution_controls")},
                     indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
