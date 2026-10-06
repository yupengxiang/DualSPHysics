#!/usr/bin/env python3
"""Metadata/PNG-only validator for fresh127; never opens scientific payloads."""
import hashlib, json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
C=json.loads((ROOT/"metadata/chain-closure.json").read_text())
V=json.loads((ROOT/"metadata/visual-review.json").read_text())
P=json.loads((ROOT/"metadata/png-hashes.json").read_text())
def sh(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()
assert C["fresh_id"]=="fresh127" and V["status"]=="visual-approved-by-delegated-agent"
assert C["status"]==V["status"] and C["case_credit"]==0
assert C["arrays_read_by_reviewer"] is False and C["scientific_payload_read_or_hashed_by_reviewer"] is False
assert V["agent_personally_viewed_all_contact_sheets"] is True and V["agent_personally_viewed_all_key_frames"] is True
assert P["counts"]=={"contact_sheets_viewed":51,"key_frames_viewed":9}
for s in ("gencase","basic_initial_qa","native","native_frame0_qa","typed","xmf","render"):
    assert s in C["producer_chain"]
assert C["producer_chain"]["gencase"]["receipt"]["status"]=="completed"
assert C["producer_chain"]["basic_initial_qa"]["pass_result"] is True
assert C["producer_chain"]["native_frame0_qa"]["pass_result"] is True
assert C["producer_chain"]["typed"]["frames"]==1201 and C["producer_chain"]["typed"]["particles"]==83233
assert C["producer_chain"]["typed"]["solver_dimension"]==3 and C["producer_chain"]["typed"]["partvtk_validation_all_passed"] is True
assert C["producer_chain"]["xmf"]["frames"]==1201 and C["producer_chain"]["xmf"]["particles"]==83233
assert C["producer_chain"]["xmf"]["expected_dimension"]==3
assert C["producer_chain"]["render"]["frames"]==1201 and C["producer_chain"]["render"]["source_frames"]==1201
assert C["producer_chain"]["render"]["all_frames_rendered"] is True
assert C["producer_chain"]["render"]["actual_times_preserved_exactly"] is True
assert C["producer_chain"]["render"]["native_identity_axis_preserved"] is True
assert C["producer_chain"]["render"]["nonfinite_active_states"]==0
assert C["scope_separation"]["canonical_production_approval"] is False
for x in P["contact_sheets"]+P["key_frames"]:
    p=Path(x["path"]); assert p.suffix.lower()==".png" and p.exists() and sh(p)==x["sha256"]
L=C["lifecycle_metadata"]
assert L["frame_diagnostics_count"]==1201 and L["reported_missing_frame_event_count"]==167
assert L["reported_maximum_missing_particles_per_frame"]==1
assert L["first_reported_missing"]["frame"]==1034 and L["last_reported_missing"]["frame"]==1200
assert L["final_uid_status"]=="not independently inferred by delegated visual review"
print("fresh127 metadata/PNG validation: PASS")
print("contact_sheets=51 key_frames=9 frames=1201 particles=83233")
print("reported_missing_events=167 max_missing_per_frame=1 final_uid=not_inferred")
