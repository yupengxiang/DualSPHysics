#!/usr/bin/env python3
"""Metadata/PNG-only verifier for the M115 delegated visual review."""
import hashlib,json
from pathlib import Path
PKG=Path(__file__).resolve().parents[1]; M=PKG/'metadata/fresh134-m115-visual-review.json'
EXPECTED={'total':194427,'fixed':158559,'moving':4210,'floating':0,'fluid':31658,'unknown':0}
KEYS=(0,97,153,219,400,718,800)
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def ok(x,msg):
 if not x: raise AssertionError(msg)
d=json.loads(M.read_text()); ok(d['source_only_package'] and d['no_science_payload_opened_or_hashed_by_source_owner'],'source safety')
rec=Path(d['actual_receipt']['path']); rpt=Path(d['actual_render_report']['path']); bed=Path(d['bed_audit_metadata']['path'])
ok(rec.exists() and sha(rec)==d['actual_receipt']['sha256'],'receipt'); ok(rpt.exists() and sha(rpt)==d['actual_render_report']['sha256'],'render report'); ok(bed.exists() and sha(bed)==d['bed_audit_metadata']['sha256'],'bed report')
R=json.loads(rpt.read_text()); B=json.loads(bed.read_text()); ok(R['frames']==801 and R['source_frames']==801 and R['all_frames_rendered'] is True,'801 render')
ok(len(R['frame_diagnostics'])==801,'diagnostic length')
for x in R['frame_diagnostics']:
 ok(x['missing']==0 and x['active']==EXPECTED['total'] and x['identity_axis_preserved'] is True,'identity/missing')
 ok(x['finite_positions_active'] is True and all(v['finite_active'] is True and v['nonfinite_active']==0 for v in x['finite_fields'].values()),'finite')
 ok(x['type_counts_active']=={'fixed':EXPECTED['fixed'],'moving':EXPECTED['moving'],'floating':0,'fluid':EXPECTED['fluid'],'unknown':0},'counts')
fr=B['frame_reports']; ok(len(fr)==801,'bed frames')
for x in fr:
 ok(x['penetration']['one_dp']['count']==0 and x['penetration']['two_dp']['count']==0,'bed bins')
 ok(x['uid_tracking']['missing_initial_uid']['count']==0 and x['uid_tracking']['unexpected_current_uid']['count']==0,'uid')
 ok(x['nonfinite_position_current_fluid_count']==0 and x['nonfinite_mass_current_fluid_count']==0,'bed finite')
ok(d['png_review']['all_contact_sheets_reviewed'] is True and len(d['png_review']['all_34_contact_sheets'])==34,'contacts')
for item in d['png_review']['all_34_contact_sheets']+d['png_review']['event_keyframes']:
 p=Path(item['path']); ok(p.exists() and sha(p)==item['sha256'],f'PNG {p}')
ok(d['delegated_visual_decision']['decision']=='visual_pass_for_M115_T100_full801','decision')
ok(d['delegated_visual_decision']['case_credit_granted_by_this_review'] is False,'credit')
ok(d['scope_separation']['canonical_legacy_source_plan_kept_distinct'] is True,'scope')
print(json.dumps({'status':'passed','case_id':d['case_id'],'frames':801,'contacts':34,'event_keys':list(KEYS),'delegated_decision':d['delegated_visual_decision']['decision'],'science_payload_opened':False},indent=2))
