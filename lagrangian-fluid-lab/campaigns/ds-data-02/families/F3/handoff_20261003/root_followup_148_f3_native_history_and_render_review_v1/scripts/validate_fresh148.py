#!/usr/bin/env python3
"""Metadata/PNG-only validation for fresh148; never opens scientific payloads."""
from pathlib import Path
import hashlib, json

HERE=Path(__file__).resolve().parents[0]
PKG=HERE.parent
META=PKG/"metadata"
SIDE=json.loads((META/"f3-native-history-and-render-review.json").read_text())
PNG=json.loads((META/"png-hashes/F3_STAGE1_DP006_P1200_AY0500.json").read_text())
DEC=json.loads((META/"visual-review/F3_STAGE1_DP006_P1200_AY0500-delegated-visual-decision.json").read_text())
CHAIN=json.loads((META/"chain-audit/F3_STAGE1_DP006_P1200_AY0500.json").read_text())

def sha(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()

def check_ref(ref):
    p=Path(ref["path"]); assert p.exists(), p
    assert sha(p)==ref["sha256"], (p, ref["sha256"], sha(p))

assert SIDE["schema"]=="ds02.f3.native-history-and-render-review.v1"
assert SIDE["anchor_role_correction"]["scope_mismatch_preserved"] is True
assert SIDE["anchor_role_correction"]["native_canonical_scope"]["sha256"]=="86562c5afee8228131d58c1b53f360eb6c6a700381c01bf807a0f268bbc675c0"
assert SIDE["anchor_role_correction"]["accepted_decision_top_scope"]["sha256"]=="49e319c0a874733707a028e916362e74e2301d6681e34bc6b717581dbd7edaeb"
assert SIDE["anchor_role_correction"]["semantic_owner_scope"]["sha256"]=="49d16330fd5267668670f166a20191bfb00c5223ad5528439630c7e62dd4c6a0"
assert len(SIDE["four_p1000_historical_native_rows"])==4
for row in SIDE["four_p1000_historical_native_rows"]:
    original=row["original_native_receipt"]
    assert original["status"]=="running" and original["returncode"] is None
    ev=row["recovery_audit_case_evidence"]
    assert ev["native_solver_completed_evidence"] is True and ev["native_log_finish_code"]==0
    assert ev["actual_native_frames"]==836 and ev["native_total_particles"]==179208
    assert ev["runtime_process_returncode_unobserved"] is True
    assert row["role_resolution"]["rerun"]=="not requested or performed"

rr=SIDE["render_review"]
assert rr["receipt"]["status"]=="completed" and rr["receipt"]["returncode"]==0
assert rr["same_handle_probe"]["visual_review_status"]=="PERSONALLY_REVIEWED_ALL_CONTACT_SHEETS_AND_NINE_KEYFRAMES"
assert rr["personal_review"]["contact_sheet_count"]==35 and rr["personal_review"]["key_frame_count"]==9
assert rr["personal_review"]["independent_case_count_increment"]==0
assert rr["actual_scope"]["physical_condition_sha256"]=="11c2f68c9ca5dd7e6aaf6194e7c07c942c120fb7f5bb8dc7d649928c598165f4"

assert PNG["contact_sheet_count"]==35 and PNG["key_frame_count"]==9
assert PNG["all_pngs_read_with_view_image"] is True
assert PNG["scientific_payload_opened_or_hashed_by_reviewer"] is False
assert [x["frame"] for x in PNG["key_frames"]]==[0,104,208,312,417,521,626,730,835]
for item in PNG["contact_sheets"]+PNG["key_frames"]:
    assert item["viewed_with_view_image"] and item["personally_viewed"]
    assert sha(item["path"])==item["sha256"], item["path"]

assert DEC["status"]=="visual-approved-by-delegated-agent"
assert DEC["agent_personally_viewed_all_contact_sheets_and_keyframes"] is True
assert DEC["precision_status"]=="not_assessed"
assert DEC["independent_case_count_increment"]==0
assert DEC["scope_separation"]["native_canonical_scope_sha256"]=="11c2f68c9ca5dd7e6aaf6194e7c07c942c120fb7f5bb8dc7d649928c598165f4"
assert CHAIN["metadata_assertions"]["render_frames"]==836
assert CHAIN["metadata_assertions"]["render_publish_status"]=="published_after_atomic_rename"
assert CHAIN["negative_boundaries"]["source_scientific_payload_opened_by_reviewer"] is False
assert CHAIN["negative_boundaries"]["source_scientific_payload_hashed_by_reviewer"] is False
assert CHAIN["negative_boundaries"]["global_case_credit"]==0
for role,ref in CHAIN["roles"].items(): check_ref(ref)
print("fresh148 validation PASS: 35 contacts + 9 keyframes; four original P1000 native OS statuses preserved; no credit")
