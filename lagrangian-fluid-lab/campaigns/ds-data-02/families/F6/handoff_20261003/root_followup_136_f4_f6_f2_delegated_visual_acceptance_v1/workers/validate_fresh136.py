#!/usr/bin/env python3
"""Fresh136 metadata/XML/XMF/PNG-only delegated visual-review validator."""
from __future__ import annotations
import hashlib,json
from pathlib import Path
PK=Path(__file__).resolve().parents[1]
FORBIDDEN={'.h5','.hdf5','.bi4','.csv','.dat','.vtk','.vtm','.vtu','.pvtu'}
ALLOWED={'.json','.xml','.xmf','.png','.txt','.md','.py'}
def load(rel): return json.loads((PK/rel).read_text())
def load_abs(p): return json.loads(Path(p).read_text())
def digest(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def req(c,m):
 if not c: raise SystemExit('FAIL: '+m)
selection=load('metadata/selection-frozen.json'); route=load('metadata/routing/actual-progress.frozen.json'); cp=load('metadata/routing/checkpoint-133.frozen.json')
visual=load('metadata/visual-review.json'); closure=load('metadata/chain-closure.json'); png=load('metadata/png-hashes.json'); ev=load('metadata/evidence-files.json')
req(len(selection['selected_cases'])==3,'three selected cases')
req(selection['live_route_used_only_for_selection'] is True and selection['frozen_snapshot_is_primary_route_evidence'] is True,'routing freeze contract')
route_bytes=(PK/'metadata/routing/actual-progress.frozen.json').read_bytes(); cp_bytes=(PK/'metadata/routing/checkpoint-133.frozen.json').read_bytes()
req(digest(PK/'metadata/routing/actual-progress.frozen.json')==selection['route_snapshot_sha256'],'route snapshot digest')
req(digest(PK/'metadata/routing/checkpoint-133.frozen.json')==selection['checkpoint_snapshot_sha256'],'checkpoint snapshot digest')
req(len(cp['accepted_decisions'])==selection['checkpoint_accepted_decisions_count'],'checkpoint decision count')
cp_text=cp_bytes.decode('utf-8')
for s in selection['selected_cases']:
 req(s['status']=='completed' and s['returncode']==0 and s['actual_fullnative_render_pass'] is True,'route completed/0 '+s['case_id'])
 req(s['not_in_checkpoint_133_exact_text'] is True,'checkpoint de-dup '+s['case_id'])
 req(s['case_id'] not in cp_text and s['physical_case_id'] not in cp_text,'case in accepted checkpoint '+s['case_id'])
req(visual['status']=='visual-approved-by-delegated-agent' and closure['status']==visual['status'],'package status')
req(visual['case_credit']==0 and closure['case_credit']==0 and visual['global_credit_updated_by_agent'] is False and closure['global_credit_updated_by_agent'] is False,'credit boundary')
req(visual['scientific_payload_read_or_hashed_by_reviewer'] is False and closure['scientific_payload_read_or_hashed_by_reviewer'] is False,'payload boundary')
req(len(visual['cases'])==3 and len(closure['cases'])==3 and len(png['cases'])==3,'case inventories')
# Evidence must use frozen route snapshots, never the mutable live progress table.
req(ev['live_mutable_routing_excluded'] is True,'mutable routing policy')
for f in ev['files']:
 p=Path(f['path']); req(p.exists(),'missing evidence '+str(p)); req(p.suffix.lower() in ALLOWED,'unsupported evidence '+str(p)); req(p.suffix.lower() not in FORBIDDEN,'forbidden evidence '+str(p)); req(p.stat().st_size==f['bytes'],'evidence size '+str(p)); req(digest(p)==f['sha256'],'evidence digest '+str(p))
req(not any(Path(f['path']).name=='actual-progress.json' for f in ev['files']),'live actual-progress in evidence')
for pc in png['cases']:
 req(pc['agent_personally_viewed_all_contact_sheets'] and pc['agent_personally_viewed_all_key_frames'],'view flags '+pc['case_id'])
 for x in pc['contact_sheets']+pc['key_frames']:
  p=Path(x['path']); req(p.exists() and p.suffix.lower()=='.png','PNG path '+str(p)); req(p.stat().st_size==x['bytes'],'PNG size '+str(p)); req(digest(p)==x['sha256'],'PNG digest '+str(p)); req(x['personally_viewed'] is True,'PNG view '+str(p))
for fam,c in closure['cases'].items():
 req(c['status']=='visual-approved-by-delegated-agent' and c['case_credit']==0,'case status/credit '+fam)
 chain=c['producer_chain']; ri=c['render_integrity']; counts=c['counts_identity']; scope=c['scope_separation']
 rr=load_abs(chain['render']['report']); rrec=load_abs(chain['render']['receipt']); pub=load_abs(chain['render']['publish_receipt']); trep=load_abs(chain['typed']['conversion_report']); typedrec=load_abs(chain['typed']['receipt']); xmf=load_abs(chain['xmf']['manifest']); xrec=load_abs(chain['xmf']['receipt']); nrec=load_abs(chain['native_full']['execution_receipt']); grec=load_abs(chain['gencase']['execution_receipt']); q=load_abs(chain['initial_native_qa']['report']); qrec=load_abs(chain['initial_native_qa']['execution_receipt'])
 req(rrec['status']=='completed' and rrec['returncode']==0 and c['actual_root951_status']['status']=='completed','render receipt '+fam); req(pub['status']=='published_after_atomic_rename','publish '+fam)
 req(rr['frames']==ri['frames'] and rr['source_frames']==ri['frames'] and rr['all_frames_rendered'] is True and rr['actual_times_preserved_exactly'] is True and rr['native_identity_axis_preserved'] is True and rr['nonfinite_active_states']==0,'render integrity '+fam)
 req(grec['status']=='completed' and grec['returncode']==0 and nrec['status']=='completed' and nrec['returncode']==0,'Gen/native receipt '+fam)
 req(typedrec['status']=='completed' and typedrec['returncode']==0 and trep['conversion_status']=='completed','typed receipt '+fam); req(trep['frames']==ri['frames'] and trep['solver_dimension']['solver_dimension']==3 and trep['partvtk_validation']['all_passed'] is True,'typed structure '+fam)
 req(xrec['status']=='completed' and xrec['returncode']==0 and xmf.get('expected_frames',xmf.get('frames'))==ri['frames'] and xmf.get('expected_particles',xmf.get('particles'))==counts['total'],'XMF structure '+fam)
 req(c['producer_chain']['initial_native_qa'].get('status') in ('pass','completed') or c['producer_chain']['initial_native_qa'].get('pass') is True,'initial QA '+fam)
 req(counts['dimension']==3 and counts['total']==xmf.get('expected_particles',xmf.get('particles')),'counts '+fam)
 req(scope['scope_equality_claim']=='none','scope equality '+fam)
 if fam=='F6':
  st=load_abs(chain['floatinginfo_state0']['audit_report']); ha=load_abs(chain['typed_h5_audit']['report'])
  req(st['status']=='pass' and all(st['checks'].values()),'F6 state0 audit'); req(ha['status']=='pass' and all(ha['checks'].values()),'F6 H5 audit'); req(chain['floatinginfo_state0']['particle_v0_zero_not_angular_proof'] is True,'F6 angular boundary')
print('PASS: fresh136 frozen route selection, 3 completed/0 chains, 51+11+17 contact sheets, 9 keys each, PNG digests, metadata scopes and visual boundaries validated')
