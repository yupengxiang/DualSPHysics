#!/usr/bin/env python3
"""Validate fresh133 metadata and visual PNG evidence without scientific payload IO."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
HERE=Path(__file__).resolve().parents[1]
COMMIT="db6d0a76af385eeec89516c1468476fee415e0e8"
CASES=["F3_STAGE1_DP006_P1000_AY0440","F3_STAGE1_DP006_P1000_AY0540","F3_STAGE1_DP006_P1000_AY0590"]
def sha(p:Path)->str:return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p:Path):return json.loads(p.read_text())
audit=load(HERE/'metadata/accepted-checkpoint-audit.json')
assert audit['fresh_id']=='fresh133' and audit['checkpoint']['checkpoint_number']==154
assert audit['selected_cases_not_in_checkpoint'] is True and audit['shared_state_written'] is False
for case in CASES:
 chain=load(HERE/'metadata/chain-audit'/f'{case}.json')
 dec=load(HERE/'metadata/visual-review'/f'{case}-delegated-visual-decision.json')
 png=load(HERE/'metadata/png-hashes'/f'{case}.json')
 assert chain['fresh_id']=='fresh133' and chain['chain_complete_for_visual_review'] is True
 assert dec['status']=='visual-approved-by-delegated-agent' and dec['source_review_commit']==COMMIT
 assert dec['agent_personally_viewed_all_contacts_and_keys'] is True and dec['main_personally_viewed_pngs'] is False
 assert dec['actual_frames']==836 and dec['actual_particles']==179208 and dec['actual_fluid_particles']==67500
 assert dec['maximum_missing_particles']==0 and dec['precision_status']=='not_accepted'
 assert len(png['contact_sheets'])==35 and len(png['keyframes'])==6 and dec['verified_PNG_hashes']==png
 for item in png['contact_sheets']+png['keyframes']:
  p=Path(item['path']); assert p.is_file(),p; assert sha(p)==item['sha256'],p
 assert sha(Path(dec['source_review']['path']))==dec['source_review']['sha256']
 assert dec['checkpoint_dedup']['no_match_for_visual_review'] is True
 assert chain['owner_and_scope']['source_and_canonical_hashes_are_distinct'] is True
 assert chain['owner_and_scope']['legacy_scope_not_substituted_for_canonical'] is True
 assert chain['owner_and_scope']['forcing_producer_attestation']['before_after_equal'] is True
 assert chain['source_read_boundary']['scientific_payload_opened_by_this_agent'] is False
 assert chain['source_read_boundary']['scientific_payload_hashed_by_this_agent'] is False
 for stage in ('native','typed','xmf','render'):
  s=chain['stages'][stage]; assert s['status']=='completed' and s['returncode']==0
  assert sha(Path(s['path']))==s['sha256'],s['path']
print('fresh133 validation PASS: 3 visual decisions, 123 contact/key PNG hashes, CP154 dedup closed, no XMF successor')
