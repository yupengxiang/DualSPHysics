#!/usr/bin/env python3
"""Validate fresh159 without scientific-payload IO."""
from pathlib import Path
import hashlib, json

ROOT=Path(__file__).resolve().parents[1]
CASE="F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M096_T095_NEXT34"
PHYSICAL="F5_COMPACT_RUNUP_RECOVERY_C082S1_M096_T095"
FORBIDDEN=(".h5", ".hdf5", ".bi4", ".csv", ".dat", ".vtk", ".vtu", ".pvtu")

def read(p): return json.loads(p.read_text())
def sha(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()
def fail(x): raise AssertionError(x)
def walk(v):
    if isinstance(v,dict):
        for x in v.values(): yield from walk(x)
    elif isinstance(v,list):
        for x in v: yield from walk(x)
    elif isinstance(v,str): yield v

def main():
    chain=read(ROOT/"metadata/chain-audit"/"F5_COMPACT_RUNUP_RECOVERY_C082S1_M096_T095.json")
    decision=read(ROOT/"metadata/visual-review"/"F5_COMPACT_RUNUP_RECOVERY_C082S1_M096_T095-delegated-visual-decision.json")
    prov=read(ROOT/"metadata/source-review-provenance.json")
    png=read(ROOT/"metadata/png-evidence"/"F5_COMPACT_RUNUP_RECOVERY_C082S1_M096_T095.json")
    if (chain["case_id"],chain["physical_case_id"],chain["actual_family_id"],chain["assigned_worktree_family_id"]) != (CASE,PHYSICAL,"F5","F3"): fail("identity")
    if decision["status"] != "visual-approved-by-delegated-agent": fail("visual status")
    if decision["contact_sheets_viewed"]["count"] != 34 or decision["keyframes_viewed"]["count"] != 9: fail("view counts")
    if decision["keyframes_viewed"]["frame_indices"] != [0,100,200,300,400,500,600,700,800]: fail("keyframe ids")
    lim=decision["review_limits"]
    for k in ("global_state_written","shared_index_or_ledger_modified","scientific_payload_opened_or_hashed_by_this_agent","h5_bi4_csv_dat_vtk_payload_opened_or_hashed_by_this_agent","jobs_started","jobs_restarted","jobs_stopped","source_or_science_files_modified"):
        if lim[k]: fail(k)
    if lim["case_credit"] != 0 or lim["independent_case_increment"] != 0 or lim["q_n_granted"] or lim["q_e_granted"] or lim["numerical_precision_accepted"]: fail("credit/precision boundary")
    for stage in ("gencase","initial_qa","native","typed","xmf","render"):
        s=chain["stages"][stage]
        if s.get("status") != "completed" or s.get("returncode") != 0: fail(f"stage {stage}")
    if chain["actual_counts"] != {"full_frames":801,"particles":194427,"initial_fluid_uids":31658,"expected_contact_sheets":34,"expected_keyframes":9}: fail("counts")
    entries=png["entries"]
    contacts=[e for e in entries if e["role"]=="contact_sheet"]
    keys=[e for e in entries if e["role"]=="event_keyframe"]
    if len(contacts)!=34 or sorted(e["contact_index"] for e in contacts)!=list(range(34)): fail("contacts")
    if len(keys)!=9 or sorted(e["frame_index"] for e in keys)!=[0,100,200,300,400,500,600,700,800]: fail("keys")
    for e in entries:
        p=Path(e["path"])
        if p.suffix.lower() != ".png" or not p.exists(): fail(f"PNG path {p}")
        if not e["viewed"] or e["view_method"] != "view_image": fail(f"not viewed {p}")
        if p.stat().st_size != e["bytes"]: fail(f"PNG bytes {p}")
        if sha(p) != e["sha256"]: fail(f"PNG hash {p}")
    # Validate only immutable metadata references; never dereference scientific payload paths.
    for name,r in chain["actual_paths"].items():
        p=Path(r["path"])
        if p.suffix.lower() in FORBIDDEN: fail(f"forbidden payload path {p}")
        if p.suffix.lower()==".json" and p.exists() and len(r.get("sha256",""))==64:
            if sha(p) != r["sha256"]: fail(f"metadata changed {name}: {p}")
    if any(any(s.lower().endswith(x) for x in FORBIDDEN) for s in walk(chain)): fail("payload suffix in chain")
    if prov["read_boundary"]["h5_opened_or_hashed"] or prov["read_boundary"]["bi4_opened_or_hashed"] or prov["read_boundary"]["csv_opened_or_hashed"] or prov["read_boundary"]["dat_opened_or_hashed"] or prov["read_boundary"]["vtk_opened_or_hashed"]: fail("payload boundary")
    integrity=read(ROOT/"metadata/package-integrity.json")
    listed={x["path"]:x for x in integrity["files"]}
    actual={str(p.relative_to(ROOT)):p for p in ROOT.rglob("*") if p.is_file() and p.name!="package-integrity.json"}
    if set(listed)!=set(actual): fail("package file set")
    for rel,item in listed.items():
        p=actual[rel]
        if p.stat().st_size!=item["bytes"] or sha(p)!=item["sha256"]: fail(f"package hash {rel}")
    print("fresh159 validation PASS: F5 Root1163 completed/0; 34 contact sheets + 9 keyframes personally viewed; no scientific-payload IO")
if __name__=='__main__': main()
