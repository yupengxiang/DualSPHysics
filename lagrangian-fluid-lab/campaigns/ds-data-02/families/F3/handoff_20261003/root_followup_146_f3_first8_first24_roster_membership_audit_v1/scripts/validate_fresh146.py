#!/usr/bin/env python3
"""Metadata-only validator for fresh146 membership proof."""
from __future__ import annotations
import hashlib,json
from pathlib import Path
PKG=Path(__file__).resolve().parents[0].parent
REPORT=PKG/"metadata/f3-first8-first24-current48-membership-audit.json"
FORBIDDEN={".bi4",".h5",".hdf5",".csv",".dat",".vtk",".vtp",".pvd",".pvtu",".png",".gif"}
def sha(p):
 h=hashlib.sha256()
 with Path(p).open("rb") as f:
  for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
 return h.hexdigest()
def main():
 r=json.loads(REPORT.read_text())
 assert r["family_id"]=="F3" and r["fresh_id"]=="fresh146"
 b=r["scientific_payload_boundary"]
 assert all(b[k] is False for k in ("opened","read","hashed","copied","png_viewed","jobs_started","shared_state_modified"))
 c=r["collection_counts"]
 assert c["first8_frozen_membership"]==8 and c["first24_ordered_manifest"]==24
 assert c["current_f3_roster"]==48 and c["current_f3_unique_physical_case_ids"]==48
 assert c["current_roster_accepted"]==35 and c["current_roster_registered_pending"]==13
 assert r["membership_proof"]["first8_is_exact_ordered_subset"] is True
 assert r["membership_proof"]["first8_case_and_physical_id_matches_current_roster"]==8
 assert r["membership_proof"]["first8_exact_canonical_sha_matches_current_roster"]==8
 assert r["membership_proof"]["first24_case_and_physical_id_matches_current_roster"]==24
 assert r["membership_proof"]["first24_relation_counts"]=={"exact_canonical_condition_sha":22,"roster_canonical_sha_missing_pending":1,"canonical_scope_alias":1}
 for s in r["authoritative_sources"].values():
  if isinstance(s,dict) and s.get("path") and s.get("declared_sha256") and Path(s["path"]).exists():
   assert sha(s["path"])==s["declared_sha256"],s["path"]
 # Ensure package itself has no forbidden scientific artefacts.
 for p in PKG.rglob("*"):
  if p.is_file(): assert p.suffix.lower() not in FORBIDDEN,p
 for x in r["render_frontier_recheck"]["known_registered_candidates"]:
  assert x["still_no_terminal_receipt"] is True
 print("fresh146 metadata validation PASS: first8=8/8, first24=24/24 IDs, roster=48")
 return 0
if __name__=="__main__": raise SystemExit(main())
