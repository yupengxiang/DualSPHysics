#!/usr/bin/env python3
"""Fresh161 metadata/PNG-only validator; never opens H5, BI4, CSV, DAT, VTK, or arrays."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DENIED={".h5",".hdf5",".bi4",".csv",".dat",".vtk",".vtu",".npy",".npz"}
def safe_json(p):
    if p.suffix.lower() in DENIED: raise AssertionError(f"payload read denied: {p}")
    return json.loads(p.read_text())
def sha(p):
    if p.suffix.lower() in DENIED: raise AssertionError(f"payload hash denied: {p}")
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()
def main():
    chain=safe_json(ROOT/"metadata/actual-chain.json"); visual=safe_json(ROOT/"metadata/visual-review.json"); png=safe_json(ROOT/"metadata/png-evidence.json"); hashes=safe_json(ROOT/"metadata/metadata-hashes.json"); decision=safe_json(next((ROOT/"decisions").glob("*-decision.json")))
    assert chain["package_id"]=="fresh161" and chain["reviewer"]=="/root/f6_endpoint_initial_qa" and chain["family_id"]=="F2"
    assert chain["global_acceptance"] is False and chain["case_alias_and_physical_identity"]["case_credit"]==0
    assert decision["decision"]=="visual-approved-by-delegated-agent" and decision["global_acceptance"] is False and decision["case_credit"]==0
    assert visual["contact_sheets_viewed"]==17 and visual["key_frames_viewed"]==9 and visual["failure_screen"]["renderer_returncode_zero"] is True
    assert visual["failure_screen"]["premature_termination_observed"] is False
    assert chain["scope_separation"]["scope_equality_claimed"] is False
    for k in ("canonical_source_scope_sha256","source_plan_scope_sha256","actual_converter_scope_sha256"): assert isinstance(chain["scope_separation"][k],str) and len(chain["scope_separation"][k])==64
    ri=chain["render_integrity"]
    assert ri["frames"]==401 and ri["source_frames"]==401 and ri["all_frames_rendered"] is True and ri["actual_times_preserved_exactly"] is True
    assert ri["finite_positions_and_fields_all_render_frames"] is True and ri["native_identity_axis_preserved"] is True
    assert (ri["frames_with_any_missing_particles"],ri["particle_frame_omissions_sum"],ri["maximum_missing_particles_single_frame"],ri["final_missing_particles"])==(238,654,3,3)
    assert len(png["contact_sheets"])==17 and len(png["key_frames"])==9
    for item in png["contact_sheets"]+png["key_frames"]:
        p=Path(item["path"]); assert p.exists() and p.suffix.lower()==".png" and item["personally_viewed"] is True and sha(p)==item["sha256"]
    for role,item in hashes["files"].items():
        p=Path(item["path"]); assert p.exists() and p.suffix.lower() not in DENIED and sha(p)==item["sha256"], role
    for name in ("gencase","initial_qa","native","typed","xmf","render"):
        n=chain["upstream_chain"][name]; assert n.get("returncode",0)==0 and n.get("status") in {"completed","published_after_atomic_rename"}
    assert chain["upstream_chain"]["initial_qa"]["report_status"]=="pass"
    assert "N3" in chain["upstream_chain"]["xmf"]["n3_contract"]
    assert chain["upstream_chain"]["render"]["published_status"]=="published_after_atomic_rename"
    assert hashes["producer_attested"]["reviewer_computed_science_payload_sha256"] is False and chain["source_boundary"]["science_payload_read_or_hashed"] is False
    print("fresh161 validator PASS: 17 contact sheets + 9 keyframes; full chain closed; no global credit; no science payload IO")
if __name__=="__main__": main()
