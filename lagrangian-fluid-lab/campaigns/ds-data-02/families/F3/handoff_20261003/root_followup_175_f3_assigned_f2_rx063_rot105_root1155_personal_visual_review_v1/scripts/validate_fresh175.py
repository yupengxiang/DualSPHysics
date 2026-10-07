#!/usr/bin/env python3
"""Validate fresh175 metadata and producer-published PNG references.

This validator never computes a PNG/scientific-payload digest. PNG SHA values are
trusted only as copied producer attestations from render-publish-receipt.json.
"""
from pathlib import Path
import json, hashlib

ROOT=Path(__file__).resolve().parents[1]
CASE="F2_STAGE1_FIRST48_EXPANSION_RX063_RY014_FILL080_ROT105_DP010_SPATIAL_REFERENCE_SAVE010"
PHYSICAL="F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX063_RY014_FILL080_ROT105"
FORBIDDEN=(".h5", ".hdf5", ".bi4", ".csv", ".dat", ".vtk", ".vtu", ".pvtu", ".ibi4")

def read(p): return json.loads(p.read_text())
def sha(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024), b""): h.update(b)
    return h.hexdigest()
def fail(msg): raise AssertionError(msg)
def walk(v):
    if isinstance(v,dict):
        for x in v.values(): yield from walk(x)
    elif isinstance(v,list):
        for x in v: yield from walk(x)
    elif isinstance(v,str): yield v

def main():
    chain=read(ROOT/"metadata/chain-audit/F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX063_RY014_FILL080_ROT105.json")
    png=read(ROOT/"metadata/png-evidence/F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX063_RY014_FILL080_ROT105.json")
    prov=read(ROOT/"metadata/source-review-provenance.json")
    if (chain["case_id"],chain["physical_case_id"],chain["actual_family_id"],chain["assigned_worktree_family_id"]) != (CASE,PHYSICAL,"F2","F3"): fail("identity")
    if chain["terminal_state"]["execution_receipt"]["status"] != "completed" or chain["terminal_state"]["execution_receipt"]["returncode"] != 0: fail("render receipt")
    if chain["terminal_state"]["publish_receipt"]["status"] != "published_after_atomic_rename" or not chain["terminal_state"]["atomic_publish"]: fail("publish")
    if chain["counts"]["frames"] != 401 or chain["counts"]["particles"] != 418104: fail("counts")
    if chain["counts"]["contact_sheets"] != 17 or chain["counts"]["keyframes_reviewed"] != 9: fail("review counts")
    if chain["actual_time_window_s"] != [0.0,4.000060622444042]: fail("time window")
    if chain["lifecycle_omissions"]["final_missing_particles"] != 3 or chain["lifecycle_omissions"]["first_missing_frame"] != 165 or chain["lifecycle_omissions"]["cumulative_particle_frame_omissions"] != 652: fail("omissions")
    lim=chain["review_limits"]
    for k in ("global_state_written","shared_index_or_ledger_modified","scientific_payload_opened_or_hashed_by_this_agent","h5_bi4_csv_dat_vtk_payload_opened_or_hashed_by_this_agent","jobs_started","jobs_restarted","jobs_stopped","source_or_science_files_modified"):
        if lim[k]: fail(k)
    if lim["case_credit"] != 0 or lim["independent_case_increment"] != 0 or lim["q_n_granted"] or lim["q_e_granted"] or lim["numerical_precision_accepted"]: fail("credit/precision boundary")
    for stage in ("gencase","native","typed","xmf","render"):
        if chain["stages"][stage]["status"] != "completed" or chain["stages"][stage]["returncode"] != 0: fail(f"stage {stage}")
    qi_stage=chain["stages"]["initial_qa"]
    if qi_stage["status"] != "completed" or qi_stage["returncode"] != 0: fail("initial QA")
    if chain["scope_roles"]["native_source_plan_condition"]["present"] is not False: fail("native source plan condition role")
    if chain["scope_roles"]["xmf_source_plan_condition"]["present"] is not False: fail("xmf source plan condition role")
    entries=png["entries"]
    contacts=[e for e in entries if e["role"]=="contact_sheet"]
    keys=[e for e in entries if e["role"]=="event_keyframe"]
    if len(contacts)!=17 or sorted(e["index"] for e in contacts)!=list(range(17)): fail("contacts")
    if len(keys)!=9 or sorted(e["frame_index"] for e in keys)!=[0,50,100,150,200,250,300,350,400]: fail("keys")
    for e in entries:
        p=Path(e["path"])
        if p.suffix.lower() != ".png" or not p.exists(): fail(f"PNG path {p}")
        if not e["viewed"] or e["view_method"] != "view_image": fail(f"not viewed {p}")
        if p.stat().st_size != e["bytes"]: fail(f"PNG producer bytes {p}")
        if len(e["producer_sha256"]) != 64: fail(f"missing producer SHA {p}")
    # Only metadata paths are dereferenced here; scientific payload suffixes are rejected.
    for ref in chain["actual_paths"].values():
        p=Path(ref["path"])
        if p.suffix.lower() in FORBIDDEN: fail(f"forbidden path {p}")
        if not p.exists(): fail(f"missing metadata path {p}")
    if any(any(s.lower().endswith(x) for x in FORBIDDEN) for s in walk(chain)): fail("scientific payload path in chain")
    if prov["read_boundary"]["h5_opened_or_hashed"] or prov["read_boundary"]["bi4_opened_or_hashed"] or prov["read_boundary"]["csv_opened_or_hashed"] or prov["read_boundary"]["dat_opened_or_hashed"] or prov["read_boundary"]["vtk_opened_or_hashed"]: fail("payload boundary")
    integrity=read(ROOT/"metadata/package-integrity.json")
    listed={x["path"]:x for x in integrity["files"]}
    actual={str(p.relative_to(ROOT)):p for p in ROOT.rglob("*") if p.is_file() and p.name != "package-integrity.json"}
    if set(listed) != set(actual): fail("package file set")
    for rel,item in listed.items():
        p=actual[rel]
        if p.stat().st_size != item["bytes"] or sha(p) != item["sha256"]: fail(f"package hash {rel}")
    print("fresh175 validation PASS: Root1155 completed/0 + atomic publish; 17 contacts and 9 keyframes viewed; producer PNG digests preserved; no scientific-payload IO")
if __name__=='__main__': main()
