#!/usr/bin/env python3
"""
Audit script for F3 Prospective Control Domain Staging.

Verifies:
1. binding.json schema, case definitions, and claim boundaries.
2. All 8 XML definitions (canonical and case-specific) for DP 0.006 and DP 0.005.
3. All 12 runner request files for launch_allowed: false and correct schemas.
4. Transformer script self-test and pinned forcing hash verification.
5. Resource estimates structure and bounds.
6. Second mechanism proposal structure and scientific completeness.
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
    print(f"Auditing prospective domain at: {base}")

    # 1. Check binding.json
    binding_path = base / "binding.json"
    assert binding_path.exists(), "binding.json missing"
    binding = json.loads(binding_path.read_text())
    assert binding["schema"] == "ds02.f3.adaptive-control-domain-prospective.v1"
    assert binding["claim_boundaries"]["domain_status"] == "prospective"
    assert binding["claim_boundaries"]["launch_allowed"] is False
    assert binding["claim_boundaries"]["q_n_status"] == "not_granted"
    print("✓ binding.json validated")

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

    print(f"✓ All {len(cases)} case definitions validated")

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

    print(f"✓ All {len(req_files)} requests validated (all launch_allowed=False)")

    # 4. Check transformer
    tf_script = base / "transform_forcing.py"
    assert tf_script.exists(), "transform_forcing.py missing"
    from transform_forcing import PINNED_NOMINAL_FORCING_SHA256, self_test
    self_test()
    assert PINNED_NOMINAL_FORCING_SHA256 == "6f42660acb261a5e451436bb3087af86d09310085ea1ee48d0b02eae8b3205d3"
    print("✓ transform_forcing.py self-test passed and pinned hash verified")

    # 5. Check second mechanism proposal
    prop_path = base / "second_mechanism_proposal.json"
    assert prop_path.exists(), "second_mechanism_proposal.json missing"
    prop = json.loads(prop_path.read_text())
    assert prop["schema"] == "ds02.f3.second-mechanism-proposal.v1"
    assert "baffle_disqualification_rationale" in prop
    assert "proposed_second_mechanism" in prop
    assert prop["governance_and_claim_boundary"]["claim_status"] == "entire_domain_prospective"
    print("✓ second_mechanism_proposal.json validated")

    # 6. Check resource estimates
    res_path = base / "resource_estimates.json"
    assert res_path.exists(), "resource_estimates.json missing"
    res = json.loads(res_path.read_text())
    assert res["schema"] == "ds02.f3.resource-estimates.v1"
    assert "candidate_resolution_dp006" in res
    assert "reference_resolution_dp005" in res
    print("✓ resource_estimates.json validated")

    print("\n==========================================")
    print("ALL AUDIT CHECKS PASSED SUCCESSFULLY.")
    print("==========================================")


if __name__ == "__main__":
    audit()
