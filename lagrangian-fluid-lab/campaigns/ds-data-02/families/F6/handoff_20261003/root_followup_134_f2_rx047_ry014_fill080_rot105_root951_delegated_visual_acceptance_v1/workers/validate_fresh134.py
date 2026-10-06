#!/usr/bin/env python3
"""Fresh134 metadata/XML and PNG-only delegated visual-review validator."""
import hashlib
import json
from pathlib import Path

PKG=Path(__file__).resolve().parents[1]
FORBIDDEN={".h5",".bi4",".csv",".dat",".vtk",".vtm",".vtu",".pvtu"}
CASE="F2_STAGE1_FIRST48_EXPANSION_RX047_RY014_FILL080_ROT105_DP010_SPATIAL_REFERENCE_SAVE010"
PHYS="F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX047_RY014_FILL080_ROT105"

def load(rel):
    return json.loads((PKG/rel).read_text())

def load_abs(path):
    return json.loads(Path(path).read_text())

def digest(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""):
            h.update(block)
    return h.hexdigest()

def req(condition, message):
    if not condition:
        raise SystemExit("FAIL: "+message)

review=load("metadata/visual-review.json")
closure=load("metadata/chain-closure.json")
png=load("metadata/png-hashes.json")
evidence=load("metadata/evidence-files.json")
req(review["status"]=="visual-approved-by-delegated-agent","review status")
req(closure["status"]==review["status"],"status mismatch")
req(review["case_id"]==CASE and review["physical_case_id"]==PHYS,"case identity")
req(closure["case_id"]==CASE and closure["physical_case_id"]==PHYS,"closure identity")
req(closure["attempt_id"].endswith("root951"),"Root951 attempt")
req(review["case_credit"]==0 and closure["case_credit"]==0,"case credit")
req(review["global_credit_updated_by_agent"] is False and closure["global_credit_updated_by_agent"] is False,"global credit")
req(review["scientific_payload_read_or_hashed_by_reviewer"] is False and closure["scientific_payload_read_or_hashed_by_reviewer"] is False,"payload claim")
req(review["agent_personally_viewed_all_contact_sheets"] is True and review["agent_personally_viewed_all_key_frames"] is True,"view evidence")
req(len(png["contact_sheets"])==17 and [x["index"] for x in png["contact_sheets"]]==list(range(17)),"contact inventory")
req(len(png["key_frames"])==9 and [x["frame"] for x in png["key_frames"]]==[0,50,100,150,200,250,300,350,400],"key inventory")
for item in png["contact_sheets"]+png["key_frames"]:
    p=Path(item["path"])
    req(p.exists(),f"missing PNG {p}")
    req(p.suffix.lower()==".png",f"non-PNG {p}")
    req(p.stat().st_size==item["bytes"],f"PNG size {p}")
    req(digest(p)==item["sha256"],f"PNG digest {p}")
req(evidence["scientific_payload_read_or_hashed_by_reviewer"] is False,"evidence payload claim")
for item in evidence["files"]:
    p=Path(item["path"])
    req(p.exists(),f"missing evidence {p}")
    req(p.suffix.lower() not in FORBIDDEN,f"forbidden evidence {p}")
    req(p.stat().st_size==item["bytes"],f"evidence size {p}")
    req(digest(p)==item["sha256"],f"evidence digest {p}")

# Producer evidence checks use metadata JSON only.
render=closure["producer_chain"]["render"]
render_receipt=load_abs(render["receipt"])
render_report=load_abs(render["report"])
publish=load_abs(render["publish_receipt"])
req(render_receipt.get("status")=="completed" and render_receipt.get("returncode")==0,"render receipt completed/0")
req(publish.get("status")=="published_after_atomic_rename","publish receipt")
req(render_report.get("frames")==401 and render_report.get("source_frames")==401,"401 frames")
req(render_report.get("all_frames_rendered") is True,"all frames")
req(render_report.get("actual_times_preserved_exactly") is True,"actual times")
req(render_report.get("native_identity_axis_preserved") is True,"identity axis")
req(render_report.get("nonfinite_active_states")==0,"nonfinite active states")
req(len(render_report.get("outputs",{}).get("contact_sheets",[]))==17,"report contact sheets")
req(closure["scope_separation"]["equality_claim"]=="none","scope equality claim")
req(closure["producer_lifecycle"]["final_uid_status"]=="not inferred by visual reviewer","UID boundary")
req(closure["producer_lifecycle"]["missing_events_are_not_final_uid_count"] is True,"missing event semantics")
req(closure["scope_separation"]["actual_converter_report_scope_sha256"]=="91caa1e6b243f3a38e2e00bc0d170b42522df263abba531f52153d7d5548ebeb","actual scope")
req(closure["scope_separation"]["canonical_physical_binding_scope_sha256"]=="1dd417a22ee0095153b3bb62763fa2a34dddf3cedd507ef8d995633c8f844eab","canonical scope")
req(closure["scope_separation"]["source_plan_scope_sha256"]=="1dd417a22ee0095153b3bb62763fa2a34dddf3cedd507ef8d995633c8f844eab","source plan scope")
req(closure["scope_separation"]["actual_converter_report_scope_sha256"]!=closure["scope_separation"]["canonical_physical_binding_scope_sha256"],"scope separation values")
req(closure["counts_identity"]["actual_gencase_producer_attested"]["total"]==418104,"GenCase total")
req(closure["counts_identity"]["actual_gencase_producer_attested"]["dimension"]==3,"GenCase dimension")
req(closure["producer_chain"]["typed"]["frames"]==401,"typed frames")
req(closure["producer_chain"]["typed"]["dimension"]==3,"typed dimension")
req(closure["visual_review_summary"]["gross_visual_screen"]["full_domain_and_event_visible"] is True,"visual domain")
print("PASS: fresh134 metadata/XML, Root951 completed/0 chain, 17 contact PNGs, 9 keyframes, lifecycle and scope boundaries validated")
