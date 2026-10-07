#!/usr/bin/env python3
"""Structural validator for the F3-assigned fresh163 F2 metadata handoff."""
from __future__ import annotations
import hashlib, json, re, sys
from pathlib import Path

PKG=Path(__file__).resolve().parents[1]
READY=PKG/"metadata/f2-remaining-metadata-readiness.json"
PROV=PKG/"metadata/source-review-provenance.json"
INTEGRITY=PKG/"metadata/package-integrity.json"
FORBIDDEN=(".h5",".bi4",".csv",".dat",".vtk",".vtu",".vtp",".png",".jpg",".jpeg",".gif",".pvsm")
EXPECTED_EXCLUDED="F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT075"

def die(msg):
    raise SystemExit("fresh163 validation failed: "+msg)
def load(p):
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e: die(f"cannot load {p}: {e}")
def walk(v, loc="$"):
    if isinstance(v,dict):
        for k,x in v.items(): yield from walk(x,loc+"."+str(k))
    elif isinstance(v,list):
        for i,x in enumerate(v): yield from walk(x,loc+f"[{i}]")
    else: yield loc,v
def is_sha(v): return isinstance(v,str) and re.fullmatch(r"[0-9a-f]{64}",v or "") is not None
def ref_ok(ref, label):
    if not isinstance(ref,dict): die(label+" missing ref")
    if not isinstance(ref.get("path"),str) or not ref["path"].endswith(".json") and not ref["path"].endswith(".xml"):
        die(label+" must reference JSON/XML only")
    if not is_sha(ref.get("sha256")): die(label+" missing sha256")

d=load(READY); p=load(PROV)
if d.get("assigned_family_id")!="F3" or d.get("actual_family_id")!="F2": die("family role mismatch")
if d.get("source_only") is not True or d.get("science_payload_read") or d.get("science_payload_hashed") or d.get("scientific_jobs_started") or d.get("shared_state_modified") or d.get("global_case_credit")!=0: die("source-only guard mismatch")
if len(d.get("cases",[]))!=10: die("expected ten audited cases")
ids=[c.get("physical_case_id") for c in d["cases"]]
if len(set(ids))!=10 or EXPECTED_EXCLUDED in ids: die("case selection mismatch")
if not any(x.get("physical_case_id")==EXPECTED_EXCLUDED for x in d.get("exclusions",[])): die("fresh162 exclusion missing")
if p.get("assigned_family_id")!="F3" or p.get("actual_family_id")!="F2": die("provenance family mismatch")
if p.get("selection_rule",{}).get("audited_rows")!=10: die("provenance selection mismatch")
for path,label in [(READY,"readiness"),(PROV,"provenance")]:
    if not path.exists(): die(label+" missing")
# No package metadata value may expose a scientific-payload pathname. Producer digests remain allowed.
for obj,label in [(d,"readiness"),(p,"provenance")]:
    for loc,v in walk(obj):
        if isinstance(v,str) and v.lower().endswith(FORBIDDEN): die(f"{label}{loc} exposes forbidden payload path")
for c in d["cases"]:
    if c.get("assigned_family_id")!="F3" or c.get("actual_family_id")!="F2": die(c["physical_case_id"]+" family role")
    s=c["source_roles"]["source_metadata"]["condition"]; rot=s["rotation"]; geom=s["geometry"]
    if s["physical_condition_sha256"] != c["native"]["request_condition_sha256"]: die(c["physical_case_id"]+" source/native condition mismatch")
    if not isinstance(rot.get("duration_s"),(int,float)) or rot["stop_s"] != rot["hold_start_s"]+rot["duration_s"]: die(c["physical_case_id"]+" motion stop")
    if rot["hold_start_s"]!=0.5 or rot["final_angle_deg"]!=-105.0 or geom["dimension"]!=3 or geom["data2d"] is not False or geom["dp_m"]!=0.01: die(c["physical_case_id"]+" controls")
    if c["gencase"]["status"]!="completed" or c["gencase"]["returncode"]!=0 or c["native"]["status"]!="completed" or c["native"]["returncode"]!=0: die(c["physical_case_id"]+" native closure")
    if c["gencase"]["total_particles"]!=418104 or c["gencase"]["fluid_particles"]!=21114 or c["gencase"]["solver_dimension_from_gencase"]!=3: die(c["physical_case_id"]+" measured GenCase counts")
    if c["gencase"]["generated_xml_counts"]!={"fixed":372840,"moving":24150,"floating":0,"fluid":21114}: die(c["physical_case_id"]+" XML count report")
    if not c["gencase"]["motion_digest_attestations"] or c["gencase"]["motion_digest_attestations"][0]["sha256"] != s["source_motion"]["source_motion_sha256"] or c["gencase"]["motion_digest_attestations"][1]["sha256"] != s["source_motion"]["source_motion_sha256"]: die(c["physical_case_id"]+" GenCase motion attestation")
    if c["native"]["native_launch_motion_digest"] != s["source_motion"]["source_motion_sha256"] or c["native"]["native_after_motion_digest"] != s["source_motion"]["source_motion_sha256"]: die(c["physical_case_id"]+" native motion attestation")
    if len(c.get("typed",[]))!=1 or len(c.get("xmf",[]))!=1: die(c["physical_case_id"]+" typed/XMF multiplicity")
    t=c["typed"][0]; x=c["xmf"][0]; l=t["lifecycle"]
    if t["conversion_status"]!="completed" or t["receipt_status"]!="completed" or t["returncode"]!=0 or t["frames"]!=401 or t["particles"]!=418104: die(c["physical_case_id"]+" typed closure")
    if l["frame_summary_count"]!=401 or l["time_first_s"]!=0.0 or not isinstance(l["time_last_s"],(int,float)) or l["missing_particles"]["frames"]<0 or l["missing_particles"]["max"]<0: die(c["physical_case_id"]+" lifecycle summary")
    if x["receipt_status"]!="completed" or x["returncode"]!=0 or x["frames"]!=401 or x["particles"]!=418104 or x["time_count"]!=401: die(c["physical_case_id"]+" XMF closure")
    if not is_sha(t["output_sha256_producer_attested"]) or not is_sha(x["trajectory_h5_sha256_producer_attested"]): die(c["physical_case_id"]+" producer digest")
    if x["actual_converter_legacy_scope_sha256"] in {s["physical_condition_sha256"],c["native"]["request_condition_sha256"]}: die(c["physical_case_id"]+" scope roles collapsed")
    ref_ok(c["gencase"]["receipt"],c["physical_case_id"]+" GenCase receipt")
    ref_ok(c["native"]["receipt"],c["physical_case_id"]+" native receipt")
    ref_ok(t["conversion_report"],c["physical_case_id"]+" conversion report")
    ref_ok(x["manifest"],c["physical_case_id"]+" XMF manifest")
    ctrl=c["registered_render"]["controller"]
    # Current frozen controller observation is not a receipt and must not be upgraded by this source package.
    if ctrl.get("actual_receipt") is not None or ctrl.get("published0") is not False: die(c["physical_case_id"]+" render observation was upgraded")
# package-integrity covers all stable files except itself.
integ=load(INTEGRITY)
for item in integ.get("files",[]):
    q=PKG/item["path"]
    if not q.exists(): die("integrity file missing: "+item["path"])
    got=hashlib.sha256(q.read_bytes()).hexdigest()
    if got != item.get("sha256"): die("integrity mismatch: "+item["path"])
print(f"fresh163 PASS: {len(d['cases'])} F2 metadata chains; all native/typed/XMF closure and scope/lifecycle guards valid")
