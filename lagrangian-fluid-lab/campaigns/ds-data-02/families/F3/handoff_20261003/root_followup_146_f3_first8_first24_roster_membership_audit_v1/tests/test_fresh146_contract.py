from pathlib import Path
import json
PKG=Path(__file__).resolve().parents[1]
def test_membership_counts_and_scope_disclosures():
 r=json.loads((PKG/"metadata/f3-first8-first24-current48-membership-audit.json").read_text())
 assert r["collection_counts"]["current_f3_roster"]==48
 assert r["membership_proof"]["first24_relation_counts"]["canonical_scope_alias"]==1
 assert r["membership_proof"]["first24_relation_counts"]["roster_canonical_sha_missing_pending"]==1
 assert r["scope_role_preservation"]["legacy_aliases_never_collapsed"] is True
def test_no_credit_or_payload_access():
 r=json.loads((PKG/"metadata/f3-first8-first24-current48-membership-audit.json").read_text())
 assert r["scientific_payload_boundary"]["opened"] is False
 assert r["scope_role_preservation"]["no_visual_or_precision_credit_granted_by_this_audit"] is True
