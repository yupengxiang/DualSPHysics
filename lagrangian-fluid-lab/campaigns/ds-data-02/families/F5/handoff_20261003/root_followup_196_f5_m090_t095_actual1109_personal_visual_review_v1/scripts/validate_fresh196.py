#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def load(rel): return json.loads((ROOT/rel).read_text())
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for c in iter(lambda:f.read(1024*1024), b''):
            h.update(c)
    return h.hexdigest()

def require(cond,msg):
    if not cond: raise AssertionError(msg)

manifest=load('manifest.json')
require(manifest['manifest_excludes_self'] is True, 'manifest self exclusion')
require(manifest['source_only'] is True, 'source_only')
require(manifest['science_payloads_copied'] is False, 'payload copied')
require(manifest['scientific_jobs_started_by_source_agent'] is False, 'job started')
require(manifest['shared_state_written_by_source_agent'] is False, 'shared state')
for item in manifest['files']:
    p=ROOT/item['path']; require(p.is_file(), f'missing package file {p}')
    require(p.stat().st_size==item['bytes'], f'bytes {item["path"]}')
    require(sha(p)==item['sha256'], f'sha {item["path"]}')

r=load('metadata/actual-render-metadata.json')
require(r['attempt_id']=='root-stage1-f5-m090_t095-source179-actual1055-bed0-full801-original116023-frozen-progress-root1109','attempt')
require(r['execution_receipt']['status']=='completed' and r['execution_receipt']['returncode']==0,'render receipt')
require(r['publish_receipt']['status']=='published_after_atomic_rename','publish')
require(r['render_integrity']['frames']==801 and r['render_integrity']['source_frames']==801,'frames')
require(r['render_integrity']['contact_sheet_count']==34 and r['render_integrity']['keyframe_count']==9,'view counts')
require(r['source_agent_science_payload_io']['raw_h5_bi4_csv_dat_vtk_read'] is False,'raw read')
require(r['source_agent_science_payload_io']['raw_h5_bi4_csv_dat_vtk_hash'] is False,'raw hash')

b=load('metadata/bed-audit-metadata.json')
require(b['report_flags']['diagnostic_only'] is True,'bed diagnostic')
require(b['scope']['zero_one_dp_and_two_dp_bins_are_not_sub_dp_proof'] is True,'subdp guard')
require(b['all_frame_metadata_aggregate']['frames_scanned']==801,'bed frames')
require(b['all_frame_metadata_aggregate']['missing_uid_count_max']==0,'uid')

p=load('metadata/png-visual-evidence.json')
require(p['all_actual_contact_sheets_reviewed'] is True and len(p['contact_sheets'])==34,'contacts')
require(p['all_nine_keyframes_reviewed'] is True and len(p['keyframes'])==9,'keys')
require(all(x['reviewed'] and len(x['producer_attested_sha256'])==64 for x in p['contact_sheets']+p['keyframes']),'producer png attestations')
require(p['source_agent_science_payload_io']['published_png_hashes_computed_by_source_agent'] is False,'png rehash')

v=load('metadata/visual-decision.json')
require(v['decision']['standalone_first_stage_visual_approved'] is True,'visual decision')
require(v['decision']['severe_visual_failure'] is False,'severe')
require(v['decision']['weak_wave_only'] is True,'weak wave')
require(v['decision']['strict_container_guarantee'] is False,'container')
require(v['decision']['numerical_precision_accepted'] is False,'precision')
require(v['decision']['q_n_granted'] is False and v['decision']['independent_case_count_increment']==0,'credit')
require(v['scope_and_negative_evidence']['A_B_historical_failures_preserved'] is True,'A/B')

u=load('metadata/upstream-evidence.json')
require(u['scope_roles']['roles_remain_distinct'] is True,'scope roles')
require(u['scope_roles']['cross_resolution_claim'] is False,'cross resolution')
require(u['source_agent_science_payload_io']['raw_science_payload_copied'] is False,'upstream copy')
print('PASS fresh196: 801-frame M090_T095 personal visual review; 34 contacts + 9 keyframes; metadata-only package')
