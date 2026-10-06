#!/usr/bin/env python3
"""Fresh135 metadata/XML and PNG-only delegated visual-review validator."""
import hashlib,json
from pathlib import Path
PK=Path(__file__).resolve().parents[1]
FORBIDDEN={'.h5','.hdf5','.bi4','.csv','.dat','.vtk','.vtm','.vtu','.pvtu'}
def load(rel):return json.loads((PK/rel).read_text())
def load_abs(p):return json.loads(Path(p).read_text())
def digest(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def req(c,m):
 if not c:raise SystemExit('FAIL: '+m)
review=load('metadata/visual-review.json'); closure=load('metadata/chain-closure.json'); png=load('metadata/png-hashes.json'); ev=load('metadata/evidence-files.json')
case='F6_STAGE1_ANGULAR_RELEASE_DXYZ_S0875_YAWP06_DP025'
req(review['status']=='visual-approved-by-delegated-agent','review status');req(closure['status']==review['status'],'status mismatch')
req(review['case_id']==case and review['physical_case_id']==case,'review identity');req(closure['case_id']==case and closure['physical_case_id']==case,'closure identity')
req(closure['case_credit']==0 and review['case_credit']==0,'case credit');req(closure['global_credit_updated_by_agent'] is False and review['global_credit_updated_by_agent'] is False,'global credit')
req(review['scientific_payload_read_or_hashed_by_reviewer'] is False and closure['scientific_payload_read_or_hashed_by_reviewer'] is False,'payload boundary')
req(review['agent_personally_viewed_all_contact_sheets'] and review['agent_personally_viewed_all_key_frames'],'view evidence')
req(set(['mechanism','initial_state','all_contact_sheets','key_frames','failure_screen']) <= set(review['observations']),'visual observations')
req(len(png['contact_sheets'])==11 and [x['index'] for x in png['contact_sheets']]==list(range(11)),'contact inventory')
req(len(png['key_frames'])==9 and [x['frame'] for x in png['key_frames']]==[0,24,48,72,96,120,168,192,240],'key inventory')
for x in png['contact_sheets']+png['key_frames']:
 p=Path(x['path']);req(p.exists(),'missing PNG '+str(p));req(p.suffix.lower()=='.png','non-PNG');req(p.stat().st_size==x['bytes'],'PNG size');req(digest(p)==x['sha256'],'PNG digest')
req(ev['scientific_payload_read_or_hashed_by_reviewer'] is False,'evidence payload boundary')
for x in ev['files']:
 p=Path(x['path']);req(p.exists(),'missing evidence '+str(p));req(p.suffix.lower() not in FORBIDDEN,'forbidden evidence '+str(p));req(p.stat().st_size==x['bytes'],'evidence size '+str(p));req(digest(p)==x['sha256'],'evidence digest '+str(p))
chain=closure['producer_chain'];render=chain['render'];typed=chain['typed'];xmf=chain['xmf'];state=chain['floatinginfo_state0'];h5=chain['typed_h5_audit']
rr=load_abs(render['report']);rrec=load_abs(render['receipt']);pub=load_abs(render['publish_receipt']);trep=load_abs(typed['conversion_report']);xman=load_abs(xmf['manifest']);xrec=load_abs(xmf['receipt']);s0=load_abs(state['audit_report']);ha=load_abs(h5['report'])
req(rrec['status']=='completed' and rrec['returncode']==0,'Root951 receipt');req(pub['status']=='published_after_atomic_rename','publish receipt')
req(rr['frames']==241 and rr['source_frames']==241 and rr['all_frames_rendered'] is True,'render frames');req(rr['actual_times_preserved_exactly'] is True,'actual times');req(rr['native_identity_axis_preserved'] is True,'identity axis');req(rr['nonfinite_active_states']==0,'nonfinite active states');req(len(rr['outputs']['contact_sheets'])==11,'report contacts')
req(trep['conversion_status']=='completed' and trep['frames']==241 and trep['particles']==417505,'typed report');req(trep['solver_dimension']['solver_dimension']==3,'3D');req(trep['partvtk_validation']['all_passed'] is True,'PartVTK report')
req(xman['expected_frames']==241 and xman['expected_particles']==417505 and xman['producer_scope_schema']=='ds-data-02.physical-binding.v1','XMF manifest');req(xrec['status']=='completed' and xrec['returncode']==0,'XMF receipt')
req(s0['status']=='pass' and all(s0['checks'].values()),'state0 omega audit');req(ha['status']=='pass' and all(ha['checks'].values()),'H5 audit')
life=closure['producer_lifecycle'];req(life['transient_missing_frame_count']==234,'frame omission count');req(life['particle_frame_omission_sum']==1624,'particle-frame events');req(life['maximum_missing_particles_per_frame']==7,'max missing');req(life['missing_events_are_not_final_uid_count'] is True,'UID boundary')
sc=closure['scope_separation'];req(sc['equality_claim']=='none','scope equality');req(sc['source_canonical_physical_binding_scope_sha256']!=sc['actual_converter_report_scope_sha256'],'scope separation')
req(closure['angular_state']['particle_v0_zero_is_not_angular_velocity_proof'] is True,'angular boundary')
print('PASS: fresh135 metadata/XML, Root951 completed/0 chain, Root582/658 audits, 11 contact sheets, 9 keyframes, lifecycle and scope boundaries validated')
