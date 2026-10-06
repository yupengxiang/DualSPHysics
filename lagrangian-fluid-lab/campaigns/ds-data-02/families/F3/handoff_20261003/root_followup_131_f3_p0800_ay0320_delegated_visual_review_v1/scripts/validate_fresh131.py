#!/usr/bin/env python3
"""Validate fresh131 metadata and PNG evidence without opening scientific payloads."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
HERE=Path(__file__).resolve().parents[1]
CASE="F3_STAGE1_DP006_P0800_AY0320"
def sha(p:Path)->str:return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p:Path):return json.loads(p.read_text())
cp=load(HERE/'metadata/accepted-checkpoint-audit.json')
assert cp['checkpoint']['checkpoint_number']==147
assert cp['checkpoint']['accepted_complete_independent_cases']==222
assert cp['shared_state_written'] is False
wait=load(HERE/'metadata/wait-census.json')
assert wait['selected_ready_count']==1 and wait['wait_count']==3
assert wait['selected_case']==CASE
chain=load(HERE/'metadata/chain-audit'/f'{CASE}.json')
dec=load(HERE/'metadata/visual-review'/f'{CASE}-delegated-visual-decision.json')
png=load(HERE/'metadata/png-hashes'/f'{CASE}.json')
assert chain['chain_complete_for_visual_review'] is True
assert dec['status']=='visual-approved-by-delegated-agent'
assert dec['agent_personally_viewed_all_contacts_and_keys'] is True
assert dec['main_personally_viewed_pngs'] is False
assert dec['actual_frames']==836 and dec['actual_particles']==179208 and dec['actual_fluid_particles']==67500
assert dec['maximum_missing_particles']==0 and dec['precision_status']=='not_accepted'
assert len(png['contact_sheets'])==35 and len(png['keyframes'])==6
assert dec['verified_PNG_hashes']==png
for item in png['contact_sheets']+png['keyframes']:
 p=Path(item['path']); assert p.is_file(),p; assert sha(p)==item['sha256'],p
assert sha(Path(dec['source_review']['path']))==dec['source_review']['sha256']
assert dec['checkpoint_dedup']['no_match_for_visual_review'] is True
assert chain['owner_and_scope']['scope_hash_semantics']['legacy_scope_not_substituted_for_canonical'] is True
# Verify the six provenance layers using only small JSON/XML metadata files; the H5 attestation is producer-reported.
for key in ('canonical_source_owner','source_prepared_input_report','generated_xml_attestation','genuine_gencase_receipt','parent_initial_qa'):
 r=chain['owner_and_scope'][key]; p=Path(r['path']); assert p.is_file(),p; assert sha(p)==r['sha256'],p
assert chain['owner_and_scope']['scope_hash_semantics']['canonical_and_actual_scope_sha256_equal_in_this_case'] is True
assert chain['source_read_boundary']['scientific_payload_opened_by_this_agent'] is False
assert chain['source_read_boundary']['scientific_payload_hashed_by_this_agent'] is False
for stage in ('native','typed','xmf','render'):
 s=chain['stages'][stage]; assert s['status']=='completed' and s['returncode']==0
 p=Path(s['path']); assert p.is_file(),p; assert sha(p)==s['sha256'],p
for extra in [('typed','report_path','report_sha256'),('xmf','manifest_path','manifest_sha256'),('xmf','xml_path','xml_sha256'),('render','report_path','report_sha256'),('render','publish_receipt_path','publish_receipt_sha256')]:
 s=chain['stages'][extra[0]]; p=Path(s[extra[1]]); assert p.is_file(),p; assert sha(p)==s[extra[2]],p
print('fresh131 validation PASS: AY0320 terminal render0, 35 contact/key PNG hashes, 3 exact WAIT candidates, de-dup closed')
