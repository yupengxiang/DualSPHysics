from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.r3_g2_boundary_policy import (
    DEFAULT_MANIFEST,
    DEFAULT_POLICY,
    DEFAULT_REPORT,
    DEFAULT_SEMANTICS,
    build_report,
)


LAB = Path(__file__).resolve().parents[1]


def test_release_boundary_policy_contract_is_consistent_but_not_admitted():
    report = build_report(DEFAULT_MANIFEST, DEFAULT_SEMANTICS, DEFAULT_POLICY, DEFAULT_REPORT)
    assert report["checks"]["policy_contract_pass"]
    assert report["case_count"] == 12
    assert report["summary"] == {
        "semantic_wall_visibility_pass_count": 9,
        "policy_contract_pass_count": 12,
        "candidate_documented_case_count": 9,
        "review_required_case_count": 3,
        "formal_wall_visibility_admission_count": 0,
    }
    assert all(not case["wall_visibility_admitted"] for case in report["cases"])


def test_only_implicit_cap_cases_are_marked_for_review():
    report = build_report(DEFAULT_MANIFEST, DEFAULT_SEMANTICS, DEFAULT_POLICY, DEFAULT_REPORT)
    cases = {case["case_id"]: case for case in report["cases"]}
    assert {
        case_id for case_id, case in cases.items() if case["policy_review_required"]
    } == {"F1_center_obstacle", "F1_twin_obstacle", "F3_baffled_slosh"}
    assert cases["F1_center_obstacle"]["components"][1]["review_status"] == (
        "pending_human_or_rule_confirmation"
    )
    assert cases["F1_center_obstacle"]["components"][1]["rim_policy"] == (
        "review_required_implicit_cap"
    )
    assert cases["F1_center_obstacle"]["components"][1]["pending_implicit_cap"]
    assert cases["F1_center_obstacle"]["components"][1]["errors"] == []


def test_open_faces_must_match_semantic_audit(tmp_path):
    manifest = json.loads(DEFAULT_MANIFEST.read_text())
    semantics = json.loads(DEFAULT_SEMANTICS.read_text())
    policy = json.loads(DEFAULT_POLICY.read_text())
    release_dir = tmp_path / "release" / "v0.1-development"
    campaign_dir = tmp_path / "campaigns" / "v0.1-candidate"
    release_dir.mkdir(parents=True)
    campaign_dir.mkdir(parents=True)
    manifest_path = release_dir / "manifest.json"
    policy_path = release_dir / "boundary-component-policy.json"
    semantics_path = campaign_dir / "semantics.json"
    report_path = tmp_path / "audit.json"
    manifest["boundary_policy"] = policy_path.name
    policy["semantics_report_ref"] = "../../campaigns/v0.1-candidate/semantics.json"
    policy["cases"][0]["components"][0]["open_faces"] = ["bottom"]
    manifest_path.write_text(json.dumps(manifest))
    policy_path.write_text(json.dumps(policy))
    semantics_path.write_text(json.dumps(semantics))

    report = build_report(manifest_path, semantics_path, policy_path, report_path)
    assert not report["checks"]["policy_contract_pass"]
    case = next(item for item in report["cases"] if item["case_id"] == "F1_dam_break_plain")
    assert not case["policy_contract_pass"]
    assert any("open_faces" in error for error in case["errors"])


def test_policy_json_is_explicitly_candidate_only():
    policy = json.loads(DEFAULT_POLICY.read_text())
    assert policy["acceptance_status"] == "candidate_policy_contract_only"
    assert any("not upgraded" in claim for claim in policy["non_claims"])
    assert all(
        component["review_status"] != "confirmed"
        for case in policy["cases"]
        for component in case["components"]
    )


@pytest.mark.parametrize(
    "mutation,expected_path",
    [
        (lambda policy: policy.update({"bogus_root_field": True}), "policy"),
        (lambda policy: policy["cases"][0].update({"bogus_case_field": True}), "policy.cases[0]"),
        (
            lambda policy: policy["cases"][0]["components"][0].update({"bogus_component_field": True}),
            "policy.cases[0].components[0]",
        ),
    ],
)
def test_policy_rejects_unknown_fields_like_schema_additional_properties_false(
    tmp_path, mutation, expected_path
):
    manifest = json.loads(DEFAULT_MANIFEST.read_text())
    semantics = json.loads(DEFAULT_SEMANTICS.read_text())
    policy = json.loads(DEFAULT_POLICY.read_text())
    mutation(policy)

    release_dir = tmp_path / "release" / "v0.1-development"
    campaign_dir = tmp_path / "campaigns" / "v0.1-candidate"
    release_dir.mkdir(parents=True)
    campaign_dir.mkdir(parents=True)
    manifest_path = release_dir / "manifest.json"
    policy_path = release_dir / "boundary-component-policy.json"
    semantics_path = campaign_dir / "semantics.json"
    report_path = tmp_path / "audit.json"
    manifest["boundary_policy"] = policy_path.name
    policy["semantics_report_ref"] = "../../campaigns/v0.1-candidate/semantics.json"
    manifest_path.write_text(json.dumps(manifest))
    policy_path.write_text(json.dumps(policy))
    semantics_path.write_text(json.dumps(semantics))

    report = build_report(manifest_path, semantics_path, policy_path, report_path)
    assert not report["checks"]["policy_contract_pass"]
    assert any(expected_path in error and "unknown field" in error for error in report["global_errors"])
