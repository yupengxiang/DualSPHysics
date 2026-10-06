#!/usr/bin/env python3
"""Metadata-only validator for fresh190 membership audit."""
from __future__ import annotations
import hashlib, json, sys
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SCIENCE_SUFFIXES=(".bi4", ".h5", ".csv", ".dat", ".vtk", ".png")

def read(rel):
    p=ROOT/rel
    return json.loads(p.read_text())

def key_from_current(x):
    return (x["physical_case_id"],x["key"]["canonical_physical_condition_sha256"])

def key_from_set(x):
    return (x["physical_case_id"],x["physical_condition_sha256"])

def fail(msg):
    raise AssertionError(msg)

def main(write_report=False):
    audit=read("metadata/membership-audit.json")
    vis=read("metadata/first8-visual-subset.json")
    first24=read("metadata/first24-source-set.json")
    current=read("metadata/current48-membership.json")
    accepted=read("metadata/current-accepted-f5.json")
    checks={}
    checks["source_only_flags"] = audit["source_only"] and not audit["science_payload_read_or_hashed_by_source_agent"] and not audit["jobs_started"] and not audit["shared_state_modified"] and audit["case_credit"]==0 and not audit["q_n_granted"]
    checks["first8_visual_count"] = len(vis["cases"])==8 and len({key_from_set(x) for x in vis["cases"]})==8
    checks["first8_parent_count"] = len(first24["parent_conditions"])==8 and len({key_from_set(x) for x in first24["parent_conditions"]})==8
    checks["first24_count"] = len(first24["all_members"])==24 and len({key_from_set(x) for x in first24["all_members"]})==24
    curkeys={key_from_current(x) for x in current["rows"]}
    checks["current48_count"] = len(current["rows"])==48 and len(curkeys)==48
    checks["current48_category_counts"] = dict(Counter(x["membership"] for x in current["rows"]))=={"endpoint":2,"mother_full801":12,"next34":34}
    vkeys={key_from_set(x) for x in vis["cases"]}
    pkeys={key_from_set(x) for x in first24["parent_conditions"]}
    f24keys={key_from_set(x) for x in first24["all_members"]}
    checks["set_relations"] = len(vkeys&curkeys)==8 and len(pkeys&curkeys)==2 and len(f24keys&curkeys)==14 and len(curkeys-f24keys)==34 and len(f24keys-curkeys)==10
    akeys={key_from_set(x) for x in accepted["records"]}
    checks["accepted_checkpoint_f5"] = accepted["f5_accepted_count"]==11 and len(akeys)==11 and akeys <= curkeys
    checks["scope_roles_explicit"] = all(x["source_roles"]["native_canonical_scope_sha256"] is None and x["source_roles"]["xmf_scope_sha256"] is None and isinstance(x["source_roles"]["native_canonical_scope_status"], str) and isinstance(x["source_roles"]["xmf_scope_status"], str) for x in current["rows"])
    checks["no_science_payload_files"] = not any(p.suffix.lower() in SCIENCE_SUFFIXES for p in ROOT.rglob("*") if p.is_file())
    # The manifest deliberately excludes both itself and this report.
    manifest=read("manifest.json")
    checks["manifest_exclusions"] = manifest.get("manifest_excludes_self") is True and manifest.get("manifest_excludes_validator_report") is True and "metadata/fresh190-validator-report.json" not in manifest.get("files",{})
    checks["all_checks"] = all(checks.values())
    result={"schema":"ds02.f5.fresh190.validator-report.v1","checks":checks,"all_checks_pass":checks["all_checks"],"package_root":str(ROOT),"source_only":True,"payload_policy":"No scientific payload IO or hashing by source preparation."}
    if write_report:
        (ROOT/"metadata/fresh190-validator-report.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print(json.dumps(result,sort_keys=True))
    return 0 if result["all_checks_pass"] else 1

if __name__=="__main__":
    sys.exit(main("--write-report" in sys.argv[1:]))
