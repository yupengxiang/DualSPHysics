#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,pathlib
PKG=pathlib.Path(__file__).resolve().parents[1]
FORBIDDEN={".h5",".hdf5",".bi4",".csv",".dat",".vtk",".vtu",".pvd"}
def digest(p):
    assert p.suffix.lower() not in FORBIDDEN, p
    z=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): z.update(b)
    return z.hexdigest()
def load(n): return json.loads((PKG/"metadata"/n).read_text())
def check(ref):
    p=pathlib.Path(ref["path"]); assert p.is_file(),p; assert digest(p)==ref["sha256"],p
def main():
    v=load("visual-review.json"); e=load("png-evidence.json"); c=load("chain-closure.json")
    assert v["status"]=="visual-approved-by-delegated-agent" and v["case_credit"]==0
    assert v["all_contact_sheets_and_keys_personally_viewed"] is True
    assert c["scope_separation"]["scope_equality_not_claimed"] is True
    assert c["native_identity_and_counts"]["particles"]==418104 and c["native_identity_and_counts"]["dimension"]==3
    last=c["actual_terminal_chain"][-1]
    assert last["frames"]==401 and last["all_frames_rendered"] is True and last["actual_times_preserved_exactly"] is True and last["native_identity_axis_preserved"] is True and last["nonfinite_active_states"]==0
    for s in c["actual_terminal_chain"]:
        r=s["receipt"]; check(r); assert r["status"]=="completed" and r["returncode"]==0
        for k in ("report","generated_xml","manifest","xmf_xml","animation_report","publish_receipt"):
            if k in s: check(s[k])
    assert e["all_contact_sheets_viewed"] and len(e["contact_sheets"])==17
    assert e["all_key_frames_viewed"] and len(e["key_frames"])==9
    for r in e["contact_sheets"]+e["key_frames"]: check(r)
    for p in PKG.rglob("*"):
        if p.is_file() and p.suffix.lower() in FORBIDDEN: raise AssertionError(p)
    print("fresh153 validation PASS: terminal chain, 401-frame metadata, 17 contacts, 9 keys, scope split, case_credit=0")
if __name__=="__main__": main()
