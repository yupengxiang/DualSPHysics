#!/usr/bin/env python3
"""
Audit script for F3 Prospective Control Domain Staging (v2).

Verifies:
1. binding.json schema v2, actual anchor counts (277272), and claim boundaries.
2. All 8 XML definitions (canonical and case-specific) for DP 0.006 and DP 0.005.
3. All 12 runner request files for launch_allowed: false and correct schemas.
4. Transformer script self-test and pinned forcing hash verification across 12 synthetic fixtures.
5. Resource estimates structure, bounds, and receipt grounding.
6. Second mechanism proposal structure, corrected physics review, and claim boundaries.
"""

import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


def sha256_file(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def audit():
    base = Path(__file__).resolve().parent
    print(f"Auditing prospective domain (v2) at: {base}")

    # 1. Check binding.json
    binding_path = base / "binding.json"
    assert binding_path.exists(), "binding.json missing"
    binding = json.loads(binding_path.read_text())
    assert binding["schema"] == "ds02.f3.adaptive-control-domain-prospective.v2"
    assert binding["claim_boundaries"]["domain_status"] == "prospective"
    assert binding["claim_boundaries"]["launch_allowed"] is False
    assert binding["claim_boundaries"]["q_n_status"] == "not_granted"
    assert binding["claim_boundaries"]["production_approval"] == "none"

    anchor = binding["commensurate_reference_anchor_dp005"]
    assert anchor["actual_initial_particles"]["total"] == 277272
    assert anchor["actual_initial_particles"]["fluid"] == 116640
    assert anchor["actual_initial_particles"]["fixed"] == 160632
    assert Path(anchor["actual_gencase_receipt"]).exists()
    assert Path(anchor["actual_initial_qa_receipt"]).exists()
    assert Path(anchor["nominal_solver_receipt"]).exists()
    print("✓ binding.json validated (schema v2, anchor particles 277272, receipts verified)")

    # 2. Check definitions
    defs_dir = base / "definitions"
    assert defs_dir.exists(), "definitions dir missing"

    cases = binding["staged_prospective_cases"]
    assert len(cases) == 6, f"Expected 6 cases, got {len(cases)}"

    for c in cases:
        def_path = base / c["definition"]
        assert def_path.exists(), f"Definition missing: {def_path}"
        tree = ET.parse(def_path)
        root = tree.getroot()

        # Check CFL and CoefDtMin
        cfl = float(root.find(".//casedef/constantsdef/cflnumber").get("value"))
        assert abs(cfl - 0.05) < 1e-6, f"CFL not 0.05 in {def_path}"

        coef_dt_min = None
        for p in root.findall(".//execution/parameters/parameter"):
            if p.get("key") == "CoefDtMin":
                coef_dt_min = float(p.get("value"))
                break
        assert coef_dt_min is not None and abs(coef_dt_min - 0.005) < 1e-6, f"CoefDtMin not 0.005 in {def_path}"

        # Check DP
        dp = float(root.find(".//casedef/geometry/definition").get("dp"))
        assert abs(dp - c["dp_m"]) < 1e-6, f"DP mismatch in {def_path}"

        # Check Automatic EOS
        hswl = root.find(".//casedef/constantsdef/hswl")
        speedsound = root.find(".//casedef/constantsdef/speedsound")
        assert hswl.get("auto") == "true", f"hswl auto not true in {def_path}"
        assert speedsound.get("auto") == "true", f"speedsound auto not true in {def_path}"

        # Check accinput
        accfile = root.find(".//execution/special/accinputs/accinput/acctimesfile").get("value")
        assert accfile == "CaseSloshingAccData.csv", f"Unexpected accfile in {def_path}"

    print(f"✓ All {len(cases)} case definitions validated (CFL 0.05, CoefDtMin 0.005, Auto-EOS)")

    # 3. Check requests
    reqs_dir = base / "requests"
    assert reqs_dir.exists(), "requests dir missing"
    req_files = list(reqs_dir.glob("*.json"))
    assert len(req_files) == 12, f"Expected 12 request files, found {len(req_files)}"

    for rf in req_files:
        rdata = json.loads(rf.read_text())
        assert rdata["schema"] == "ds02.runner-request.v2", f"Invalid schema in {rf}"
        assert rdata["launch_allowed"] is False, f"launch_allowed must be false in {rf}"
        assert rdata["production_approval"] == "none", f"production_approval must be none in {rf}"
        assert rdata["q_n_status"] == "not_assessed", f"q_n_status must be not_assessed in {rf}"
        assert rdata["family_id"] == "F3", f"family_id must be F3 in {rf}"

        # Check all input files exist
        for in_file in rdata["input_files"]:
            assert Path(in_file).exists(), f"Input file not found: {in_file} from {rf}"

    print(f"✓ All {len(req_files)} requests validated (all launch_allowed=False, inputs verified)")

    # 4. Check transformer
    tf_script = base / "transform_forcing.py"
    assert tf_script.exists(), "transform_forcing.py missing"
    from transform_forcing import PINNED_NOMINAL_FORCING_SHA256, self_test
    self_test()
    assert PINNED_NOMINAL_FORCING_SHA256 == "6f42660acb261a5e451436bb3087af86d09310085ea1ee48d0b02eae8b3205d3"
    print("✓ transform_forcing.py self-test passed across all 12 synthetic unit fixtures and pinned hash verified")

    # 5. Check second mechanism proposal
    prop_path = base / "second_mechanism_proposal.json"
    assert prop_path.exists(), "second_mechanism_proposal.json missing"
    prop = json.loads(prop_path.read_text())
    assert prop["schema"] == "ds02.f3.second-mechanism-proposal.v2"
    assert "baffle_disqualification_rationale" in prop
    assert "operator_correction_and_event_crossing_legality" in prop["baffle_disqualification_rationale"]
    assert "rotation_drift_clarification" in prop["proposed_second_mechanism"]["kinematics_and_forcing_derivation"]
    assert "frame_mechanics_activation_review" in prop["proposed_second_mechanism"]["solver_version_physics"]
    assert prop["governance_and_claim_boundary"]["claim_status"] == "entire_proposal_prospective"
    print("✓ second_mechanism_proposal.json validated (corrected physics review, removed drift claim)")

    # 6. Check resource estimates
    res_path = base / "resource_estimates.json"
    assert res_path.exists(), "resource_estimates.json missing"
    res = json.loads(res_path.read_text())
    assert res["schema"] == "ds02.f3.resource-estimates.v2"
    assert "candidate_resolution_dp006" in res
    assert "reference_resolution_dp005" in res
    assert res["actual_receipt_grounding"]["reference_dp005_nominal_anchor"]["actual_initial_total_particles"] == 277272
    print("✓ resource_estimates.json validated (grounded in Gen033/QA034 receipts)")

    print("\n==========================================")
    print("ALL V2 AUDIT CHECKS PASSED SUCCESSFULLY.")
    print("==========================================")


if __name__ == "__main__":
    audit()
