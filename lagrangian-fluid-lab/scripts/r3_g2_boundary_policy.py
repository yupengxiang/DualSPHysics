#!/usr/bin/env python3
"""Audit the candidate boundary-component policy against R3 G2 evidence.

The finite sidecar audit establishes what geometry was generated.  This
contract records the *candidate* interpretation of each generated component:
which logical faces are open, how rim triangles are treated, and whether an
implicit cap might be supported by another component.  It is intentionally a
non-admission gate: a policy document is not a physical wall validation.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
CAMPAIGN = LAB / "campaigns" / "v0.1-candidate"
RELEASE = LAB / "release" / "v0.1-development"
DEFAULT_MANIFEST = RELEASE / "manifest.json"
DEFAULT_SEMANTICS = CAMPAIGN / "r3-g2-boundary-semantics.json"
DEFAULT_POLICY = RELEASE / "boundary-component-policy.json"
DEFAULT_REPORT = CAMPAIGN / "r3-g2-boundary-policy-audit.json"

FACE_NAMES = ("bottom", "left", "right", "front", "back", "top")
TARGET_FAMILIES = {"F1", "F2", "F3"}
POLICY_SCHEMA_VERSION = "boundary-component-policy-v1"
POLICY_ACCEPTANCE_STATUS = "candidate_policy_contract_only"
RIM_POLICIES = {"exclude_open_face_rim", "review_required_implicit_cap"}
REVIEW_STATUSES = {"candidate_unresolved", "pending_human_or_rule_confirmation"}
ROLES = {"container", "solid_obstacle", "baffle", "moving_cup", "receiver", "floor"}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _ordered_faces(value: Any, *, field: str) -> tuple[str, ...] | None:
    if not isinstance(value, list) or any(not isinstance(face, str) for face in value):
        return None
    if len(set(value)) != len(value):
        return None
    if any(face not in FACE_NAMES for face in value):
        return None
    return tuple(face for face in FACE_NAMES if face in value)


def _expected_role(family: str, box: dict[str, Any]) -> str | None:
    mkbound = box.get("mkbound")
    if family == "F2":
        return {0: "moving_cup", 1: "receiver", 2: "floor"}.get(mkbound)
    if box.get("void_context"):
        return "solid_obstacle" if family == "F1" else "baffle"
    return "container"


def _policy_case_map(policy: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    errors: list[str] = []
    raw_cases = policy.get("cases")
    if not isinstance(raw_cases, list):
        return {}, ["policy cases must be an array"]
    cases: dict[str, dict[str, Any]] = {}
    for index, case in enumerate(raw_cases):
        if not isinstance(case, dict) or not isinstance(case.get("case_id"), str):
            errors.append(f"policy cases[{index}] lacks a string case_id")
            continue
        case_id = case["case_id"]
        if case_id in cases:
            errors.append(f"policy contains duplicate case_id={case_id}")
        else:
            cases[case_id] = case
    return cases, errors


def _component_map(case: dict[str, Any], *, prefix: str) -> tuple[dict[int, dict[str, Any]], list[str]]:
    errors: list[str] = []
    raw = case.get("components")
    if not isinstance(raw, list):
        return {}, [f"{prefix}: components must be an array"]
    components: dict[int, dict[str, Any]] = {}
    ids: set[str] = set()
    for index, component in enumerate(raw):
        label = f"{prefix}.components[{index}]"
        if not isinstance(component, dict):
            errors.append(f"{label} is not an object")
            continue
        mkbound = component.get("mkbound")
        if not isinstance(mkbound, int) or isinstance(mkbound, bool) or mkbound < 0:
            errors.append(f"{label} has invalid mkbound")
            continue
        component_id = component.get("component_id")
        if isinstance(component_id, str) and component_id in ids:
            errors.append(f"{prefix} contains duplicate component_id={component_id}")
        if isinstance(component_id, str):
            ids.add(component_id)
        if mkbound in components:
            errors.append(f"{prefix} contains duplicate mkbound={mkbound}")
        else:
            components[mkbound] = component
    return components, errors


def _supporting_component_ok(value: Any, *, expected_pending: bool, expected_mkbound: int,
                             prefix: str) -> list[str]:
    errors: list[str] = []
    if not expected_pending:
        if value is not None:
            errors.append(f"{prefix}: supporting_component must be null when no implicit cap is observed")
        return errors
    if not isinstance(value, dict):
        return [f"{prefix}: implicit cap needs an explicit supporting_component object"]
    if value.get("component_id") != "mkbound:0":
        errors.append(f"{prefix}: expected floor support candidate mkbound:0")
    if value.get("relationship") != "floor_support_candidate":
        errors.append(f"{prefix}: relationship must be floor_support_candidate")
    # A confirmed relationship would silently turn the heuristic observation
    # into physical acceptance.  v1 records only an unconfirmed candidate.
    if value.get("status") != "unconfirmed":
        errors.append(f"{prefix}: supporting relationship must remain unconfirmed")
    if expected_mkbound == 0:
        errors.append(f"{prefix}: component cannot support its own implicit cap")
    return errors


def _audit_case(semantic_case: dict[str, Any], policy_case: dict[str, Any] | None) -> dict[str, Any]:
    case_id = semantic_case.get("case_id", "<missing>")
    family = semantic_case.get("family")
    implicit = semantic_case.get("implicit_closures_requiring_policy") or []
    expected_pending_by_mk = {int(item["mkbound"]) for item in implicit if isinstance(item, dict) and "mkbound" in item}
    errors: list[str] = []
    if policy_case is None:
        errors.append("policy case is missing")
        return {
            "case_id": case_id,
            "family": family,
            "semantic_wall_visibility_pass": bool(semantic_case.get("wall_visibility_semantics_pass")),
            "expected_implicit_cap_mkbound": sorted(expected_pending_by_mk),
            "policy_contract_pass": False,
            "review_required": True,
            "errors": errors,
        }

    expected_review = bool(expected_pending_by_mk)
    if not isinstance(policy_case.get("review_reason"), str) or not policy_case["review_reason"].strip():
        errors.append("policy case needs a non-empty review_reason")
    if policy_case.get("review_required") is not expected_review:
        errors.append(f"review_required={policy_case.get('review_required')!r} does not match implicit-cap evidence")
    expected_status = "review_required" if expected_review else "candidate_documented"
    if policy_case.get("case_status") != expected_status:
        errors.append(f"case_status must be {expected_status!r}")

    semantic_boxes = semantic_case.get("boundary_boxes")
    if not isinstance(semantic_boxes, list):
        errors.append("semantic boundary_boxes is not an array")
        semantic_boxes = []
    expected_boxes = {}
    for box in semantic_boxes:
        if isinstance(box, dict) and isinstance(box.get("mkbound"), int):
            expected_boxes[box["mkbound"]] = box
    policy_components, component_errors = _component_map(policy_case, prefix=case_id)
    errors.extend(component_errors)
    if set(policy_components) != set(expected_boxes):
        errors.append(
            f"component mkbound set {sorted(policy_components)} does not match semantic set {sorted(expected_boxes)}"
        )

    component_results: list[dict[str, Any]] = []
    for mkbound, box in sorted(expected_boxes.items()):
        component = policy_components.get(mkbound)
        component_errors_for_item: list[str] = []
        if component is None:
            component_results.append({"mkbound": mkbound, "policy_present": False, "errors": ["component is missing"]})
            continue
        prefix = f"{case_id}/mkbound:{mkbound}"
        if component.get("component_id") != f"mkbound:{mkbound}":
            component_errors_for_item.append("component_id must be mkbound:<mkbound>")
        role = component.get("role")
        expected_role = _expected_role(str(family), box)
        if role not in ROLES or role != expected_role:
            component_errors_for_item.append(f"role must be {expected_role!r}")
        expected_open = _ordered_faces(box.get("declared_open_faces"), field="declared_open_faces")
        actual_open = _ordered_faces(component.get("open_faces"), field="open_faces")
        if expected_open is None or actual_open is None or actual_open != expected_open:
            component_errors_for_item.append(
                f"open_faces {component.get('open_faces')!r} does not equal declared_open_faces {box.get('declared_open_faces')!r}"
            )
        pending = mkbound in expected_pending_by_mk
        rim_policy = component.get("rim_policy")
        expected_rim_policy = "review_required_implicit_cap" if pending else "exclude_open_face_rim"
        if rim_policy != expected_rim_policy or rim_policy not in RIM_POLICIES:
            component_errors_for_item.append(f"rim_policy must be {expected_rim_policy!r}")
        review_status = component.get("review_status")
        expected_review_status = "pending_human_or_rule_confirmation" if pending else "candidate_unresolved"
        if review_status != expected_review_status or review_status not in REVIEW_STATUSES:
            component_errors_for_item.append(f"review_status must be {expected_review_status!r}")
        if not isinstance(component.get("review_reason"), str) or not component["review_reason"].strip():
            component_errors_for_item.append("review_reason must be a non-empty string")
        component_errors_for_item.extend(_supporting_component_ok(
            component.get("supporting_component"), expected_pending=pending,
            expected_mkbound=mkbound, prefix=prefix,
        ))
        component_results.append({
            "mkbound": mkbound,
            "component_id": component.get("component_id"),
            "role": role,
            "expected_open_faces": list(expected_open or ()),
            "actual_open_faces": list(actual_open or ()),
            "rim_policy": rim_policy,
            "review_status": review_status,
            "policy_present": True,
            "pending_implicit_cap": pending,
            "pass": not component_errors_for_item,
            "errors": component_errors_for_item,
        })
        errors.extend(component_errors_for_item)

    # This is a contract audit, not an admission audit.  Even a case with no
    # implicit cap remains candidate_unresolved and is never counted as a
    # physically accepted wall-aware case by this report.
    return {
        "case_id": case_id,
        "family": family,
        "semantic_wall_visibility_pass": bool(semantic_case.get("wall_visibility_semantics_pass")),
        "expected_implicit_cap_mkbound": sorted(expected_pending_by_mk),
        "policy_case_status": policy_case.get("case_status"),
        "policy_review_required": bool(policy_case.get("review_required")),
        "components": component_results,
        "policy_contract_pass": not errors,
        "wall_visibility_admitted": False,
        "errors": errors,
    }


def build_report(manifest_path: Path = DEFAULT_MANIFEST, semantics_path: Path = DEFAULT_SEMANTICS,
                 policy_path: Path = DEFAULT_POLICY, report_path: Path = DEFAULT_REPORT) -> dict[str, Any]:
    manifest_path = Path(manifest_path).resolve()
    semantics_path = Path(semantics_path).resolve()
    policy_path = Path(policy_path).resolve()
    global_errors: list[str] = []
    try:
        manifest = _load(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        manifest = {}
        global_errors.append(f"manifest unreadable: {error}")
    try:
        semantics = _load(semantics_path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        semantics = {}
        global_errors.append(f"semantic audit unreadable: {error}")
    try:
        policy = _load(policy_path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        policy = {}
        global_errors.append(f"policy unreadable: {error}")

    manifest_ref = manifest.get("boundary_policy")
    manifest_policy_path = manifest_path.parent / manifest_ref if isinstance(manifest_ref, str) else None
    manifest_policy_link_pass = bool(
        manifest_policy_path is not None
        and manifest_policy_path.resolve() == policy_path
        and policy_path.is_file()
    )
    if not manifest_policy_link_pass:
        global_errors.append("manifest boundary_policy does not resolve to the audited policy file")
    if policy.get("schema_version") != POLICY_SCHEMA_VERSION:
        global_errors.append(f"policy schema_version must be {POLICY_SCHEMA_VERSION!r}")
    if policy.get("acceptance_status") != POLICY_ACCEPTANCE_STATUS:
        global_errors.append(f"policy acceptance_status must remain {POLICY_ACCEPTANCE_STATUS!r}")
    rules = policy.get("policy_rules")
    if not isinstance(rules, dict):
        global_errors.append("policy_rules must be an object")
    else:
        if not isinstance(rules.get("open_faces"), str) or not rules["open_faces"].strip():
            global_errors.append("policy_rules.open_faces must be a non-empty string")
        rim_rules = rules.get("rim_policy")
        if not isinstance(rim_rules, dict):
            global_errors.append("policy_rules.rim_policy must be an object")
        else:
            for key in ("exclude_open_face_rim", "review_required_implicit_cap"):
                if not isinstance(rim_rules.get(key), str) or not rim_rules[key].strip():
                    global_errors.append(f"policy_rules.rim_policy.{key} must be a non-empty string")
        if not isinstance(rules.get("supporting_component"), str) or not rules["supporting_component"].strip():
            global_errors.append("policy_rules.supporting_component must be a non-empty string")
    if policy.get("release_id") != manifest.get("release_id"):
        global_errors.append("policy release_id does not match release manifest")
    if policy.get("manifest_ref") != manifest_path.name:
        global_errors.append("policy manifest_ref does not name the release manifest")
    semantics_ref = policy.get("semantics_report_ref")
    semantics_ref_path = policy_path.parent / semantics_ref if isinstance(semantics_ref, str) else None
    semantics_reference_pass = bool(semantics_ref_path is not None and semantics_ref_path.resolve() == semantics_path)
    if not semantics_reference_pass:
        global_errors.append("policy semantics_report_ref does not resolve to the audited semantic report")
    non_claims = policy.get("non_claims")
    if not isinstance(non_claims, list) or not non_claims or any(
        not isinstance(claim, str) or not claim.strip() for claim in non_claims
    ):
        global_errors.append("policy non_claims must be a non-empty array of strings")

    manifest_cases = {
        case.get("case_id"): case for case in manifest.get("cases", [])
        if isinstance(case, dict) and case.get("family") in TARGET_FAMILIES
    }
    semantic_cases = {
        case.get("case_id"): case for case in semantics.get("cases", [])
        if isinstance(case, dict) and case.get("family") in TARGET_FAMILIES
    }
    policy_cases, policy_case_errors = _policy_case_map(policy)
    global_errors.extend(policy_case_errors)
    manifest_ids = set(manifest_cases)
    semantic_ids = set(semantic_cases)
    policy_ids = set(policy_cases)
    if manifest_ids != semantic_ids:
        global_errors.append("manifest and semantic audit case sets differ")
    if policy_ids != semantic_ids:
        global_errors.append("policy and semantic audit case sets differ")
    case_ids = sorted(manifest_ids | semantic_ids | policy_ids)
    case_results = [
        _audit_case(semantic_cases.get(case_id, {"case_id": case_id}), policy_cases.get(case_id))
        for case_id in case_ids
    ]
    contract_case_count = sum(bool(case["policy_contract_pass"]) for case in case_results)
    review_required_count = sum(bool(case.get("policy_review_required", case.get("review_required"))) for case in case_results)
    semantic_wall_count = sum(bool(case.get("semantic_wall_visibility_pass")) for case in case_results)
    policy_contract_pass = bool(
        not global_errors
        and case_results
        and contract_case_count == len(case_results)
        and len(case_results) == len(semantic_cases) == len(manifest_cases) == len(policy_cases)
    )
    report = {
        "schema_version": 1,
        "scope": "R3 G2 candidate boundary component policy contract against logical-face semantic audit",
        "execution_status": "complete",
        "acceptance_status": POLICY_ACCEPTANCE_STATUS,
        "policy_schema_version": policy.get("schema_version"),
        "manifest": str(manifest_path.relative_to(LAB)) if manifest_path.is_relative_to(LAB) else str(manifest_path),
        "semantic_audit": str(semantics_path.relative_to(LAB)) if semantics_path.is_relative_to(LAB) else str(semantics_path),
        "policy": str(policy_path.relative_to(LAB)) if policy_path.is_relative_to(LAB) else str(policy_path),
        "checks": {
            "manifest_policy_link_pass": manifest_policy_link_pass,
            "release_id_match": policy.get("release_id") == manifest.get("release_id"),
            "semantics_reference_pass": semantics_reference_pass,
            "manifest_semantic_case_set_match": manifest_ids == semantic_ids,
            "policy_semantic_case_set_match": policy_ids == semantic_ids,
            "policy_contract_pass": policy_contract_pass,
        },
        "case_count": len(case_results),
        "cases": case_results,
        "summary": {
            "semantic_wall_visibility_pass_count": semantic_wall_count,
            "policy_contract_pass_count": contract_case_count,
            "candidate_documented_case_count": len(case_results) - review_required_count,
            "review_required_case_count": review_required_count,
            "formal_wall_visibility_admission_count": 0,
        },
        "global_errors": global_errors,
        "non_claims": [
            "The 9/12 semantic wall-visibility passes are retained as audit observations and are not upgraded by this contract.",
            "A candidate_documented component is not physically validated and remains candidate_unresolved.",
            "The three implicit-cap cases require human or explicit rule confirmation; no supporting relationship is confirmed here.",
            "This report does not establish fluid-wall contact, leakage, outlets, destinations, or experimental/physical correctness.",
        ],
    }
    report_path = Path(report_path).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--semantics", type=Path, default=DEFAULT_SEMANTICS)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    report = build_report(args.manifest, args.semantics, args.policy, args.report)
    print(json.dumps({
        "case_count": report["case_count"],
        "policy_contract_pass": report["checks"]["policy_contract_pass"],
        "semantic_wall_visibility_pass_count": report["summary"]["semantic_wall_visibility_pass_count"],
        "review_required_case_count": report["summary"]["review_required_case_count"],
        "formal_wall_visibility_admission_count": report["summary"]["formal_wall_visibility_admission_count"],
        "report": str(Path(args.report).resolve()),
    }, indent=2))


if __name__ == "__main__":
    main()
