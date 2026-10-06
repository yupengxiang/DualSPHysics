#!/usr/bin/env python3
"""Validate fresh142 without opening scientific payloads."""
from pathlib import Path
import hashlib, json, sys

ROOT=Path(__file__).resolve().parents[1]
CASE="F3_STAGE1_DP006_P1200_AY0460"
FORBIDDEN={".h5",".bi4",".csv",".dat",".vtk",".vtu",".pvtu",".pvd"}

def readj(p): return json.loads(p.read_text())
def sha(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def fail(msg): raise AssertionError(msg)

def main():
    decision=readj(ROOT/"metadata/visual-review"/(CASE+"-delegated-visual-decision.json"))
    chain=readj(ROOT/"metadata/chain-audit"/(CASE+".json"))
    png=readj(ROOT/"metadata/png-hashes"/(CASE+".json"))
    if decision["status"]!="visual-approved-by-delegated-agent": fail("unexpected visual status")
    if decision["review_limits"]["case_credit"]!=0 or decision["review_limits"]["global_state_written"]: fail("credit/global state boundary")
    if decision["review_limits"]["scientific_payload_opened_or_hashed_by_this_agent"]: fail("science boundary")
    if decision["chain_requirements"]["actual_frames"]!=836 or decision["chain_requirements"]["actual_particles"]!=179208: fail("actual counts")
    if len([x for x in png["entries"] if x["role"]=="contact_sheet"])!=35: fail("contacts")
    if len([x for x in png["entries"] if x["role"]=="event_keyframe"])!=9: fail("keys")
    for e in png["entries"]:
        p=Path(e["path"])
        if p.suffix.lower()!=".png": fail(f"non-PNG evidence: {p}")
        if not p.exists(): fail(f"missing PNG: {p}")
        if not e["viewed"] or sha(p)!=e["sha256"]: fail(f"PNG evidence mismatch: {p}")
    for st in ["native","typed","xmf","render"]:
        if chain["stages"][st]["status"]!="completed": fail(f"{st} not completed")
        if chain["stages"][st]["returncode"]!=0: fail(f"{st} return code")
    for p in ROOT.rglob("*"):
        if p.is_file() and p.suffix.lower() in FORBIDDEN: fail(f"scientific payload packaged: {p}")
    # Verify the package integrity list, excluding the list itself to avoid a self-hash cycle.
    integ=readj(ROOT/"metadata/package-integrity.json")
    listed={x["path"]:x for x in integ["files"]}
    actual={str(p.relative_to(ROOT)):p for p in ROOT.rglob("*") if p.is_file() and p.name!="package-integrity.json"}
    if set(listed)!=set(actual): fail("package file set drift")
    for rel,e in listed.items():
        if e["sha256"]!=sha(actual[rel]) or e["bytes"]!=actual[rel].stat().st_size: fail(f"package integrity: {rel}")
    print("fresh142 validation PASS: 35 contact sheets + 9 keyframes; metadata chain completed/0; no payload files")

if __name__=="__main__": main()
