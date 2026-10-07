#!/usr/bin/env python3
"""Read-only fresh226 validator; metadata only, never scientific/PNG payload."""
from pathlib import Path
import hashlib,json,re,sys
PACKAGE=Path(__file__).resolve().parents[1]
PRODUCTS=PACKAGE/'metadata/f2-final48-products.json'; PROV=PACKAGE/'metadata/source-provenance.json'; ADOPT=PACKAGE/'metadata/root1436-final48-adoption.json'; MANIFEST=PACKAGE/'manifest.json'
BASE=Path('/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_224_f5_assigned_f2_final48_primary_delivery_v1/metadata/f2-final48-products.json')
CASE='F2_STAGE1_FIRST48_EXPANSION_RX053_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010'; PHYS='F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX053_RY014_FILL080_ROT090'; CAN='03e792f100771b0c5bb1e686dfccad3f29e8d4b5b7dcc2847a6cebaa6f30563e'; LEG='2a5f6038420f2c22cb53d5bcf4718ff9af01a52422d40ed47c00e9acf835ec00'; QI='d57f12d02a35ec5bf0a67f81d2319057ea4d3957392f408fa3949a4836eefc00'; PAYLOAD_RE=re.compile(r'\.(?:h5|bi4|ibi4|csv|dat|vtk)(?:["\'/]|$)',re.I)
EXPECTED={'README.md','metadata/f2-final48-products.json','metadata/source-provenance.json','metadata/root1436-final48-adoption.json','scripts/validate_fresh226.py'}
def load(p): return json.loads(Path(p).read_text())
def dg(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def ok(v,msg):
 if not v: raise AssertionError(msg)
def ref(v,label):
 ok(isinstance(v,dict) and isinstance(v.get('path'),str),'%s path'%label); ok(re.fullmatch(r'[0-9a-f]{64}',v.get('sha256','')),'%s sha'%label)
def validate_manifest():
 m=load(MANIFEST); ok(m.get('schema')=='ds02.f5.fresh226.manifest.v1','manifest schema'); ok(m.get('self_hash_excluded') is True,'self hash')
 listed={x['path']:x for x in m['files']}; ok(set(listed)==EXPECTED,'file set')
 actual={p.relative_to(PACKAGE).as_posix() for p in PACKAGE.rglob('*') if p.is_file() and p.name!='manifest.json' and '__pycache__' not in p.parts}; ok(actual==EXPECTED,'unexpected files')
 for rel,item in listed.items():
  p=PACKAGE/rel; ok(p.is_file() and item['bytes']==p.stat().st_size and item['sha256']==dg(p),'package '+rel)
def validate_products(d):
 ok(d['schema']=='ds02.f2.final48.primary-delivery-products.v2','products schema'); ok(d['accepted_actual_product_count']==48 and d['registered_final48_count']==48 and d['pending_primary_count']==0,'48 counts'); ok(d.get('pending_case_id') is None and d.get('pending_file') is None,'pending cleared'); ok(d['status']=='48_actual_primary_products','status'); ok(d['case_credit']==0 and d['Q_N']==0 and d['Q_E']==0,'credit')
 m=d['membership']; f=m['frozen_first8_physical_case_ids']; a=m['actual_first24_physical_case_ids']; z=m['registered_final48_physical_case_ids']; ok(len(f)==8 and len(a)==24 and len(z)==48 and set(f)<=set(a)<=set(z),'membership subsets')
 rows=d['products']; ok(len(rows)==48 and len({r.get('physical_case_id') for r in rows})==48,'rows')
 ok([r['physical_case_id'] for r in rows]==z,'order')
 for r in rows:
  ok(r.get('case_credit',0) in (None,0) and r.get('case_credit_delta',0) in (None,0),'row credit '+str(r.get('physical_case_id'))); ok(r.get('Q_N',0)==0 and r.get('Q_E',0)==0,'row Q '+str(r.get('physical_case_id'))); ok(r.get('main_scientific_payload_IO',r.get('scientific_payload_IO',False)) is False,'row payload')
  ref(r.get('primary_product_metadata',{}).get('XMF_XML'),'xmf xml '+r['physical_case_id']) if r['physical_case_id']==PHYS else None
  if r['physical_case_id']==PHYS:
   ok(r['delivery_order']==28 and r['case_id']==CASE and r['physical_condition_sha256']==CAN and r['actual_converter_scope_sha256']==LEG,'new row identity/scope')
   ok(r['membership']=={'actual_first24_member':False,'frozen_first8_member':False,'membership_source':'Root1276 arrays inherited through Root1330; no lexical selection','registered_final48_member':True},'new row membership')
   masks=r['physical_scope_roles']['actual_native_XMF_plan_namespaces']; ok(isinstance(masks,dict) and masks.get('native',{}).get('source_plan_condition_sha256',{}).get('present') is False and masks.get('native',{}).get('source_plan_physical_condition_sha256',{}).get('present') is True and masks['native']['source_plan_physical_condition_sha256']['value']==CAN,'native masks')
   ok(masks.get('XMF',{}).get('source_plan_condition_sha256',{}).get('present') is False and masks['XMF'].get('source_plan_physical_condition_sha256',{}).get('present') is False,'XMF masks')
   om=r['fluid_omissions']; ok(om['final_missing_particles']==2 and om['first_missing_frame']==158 and om['cumulative_particle_frame_omissions']==387 and om['producer_attested_final_Idp_sample']==[403829,410867] and om['missing_location_state_cause_unknown'],'omissions')
   ok(r['counts_and_time']['full_native_frames']==401 and r['counts_and_time']['particle_count']==418104 and r['counts_and_time']['actual_physical_window_s']==[0.0,4.000051746876743],'new counts/time')
   pr=r['proofs'];
   for k in ['accepted_visual_decision','own_full401_QI','source_validator']: ref(pr[k],PHYS+' '+k)
   ok(pr['own_full401_QI']['sha256']==QI and pr['actual_initial_QA_explicit'] is True,'new proof closure')
   vis=r['visual']; ok(vis['personal_visual_role']['contact_count']==17 and vis['personal_visual_role']['keyframe_count']==9 and vis['published_navigation_role']['contact_count']==17 and vis['published_navigation_role']['keyframe_count']==9,'new visual counts')
# Validate source provenance and exact immutable 47-row base.
def validate_prov(p,products):
 ok(p['schema']=='ds02.f5.fresh226.source-provenance.v1' and p['source_only'] is True,'provenance'); ok(p['payload_boundary']['jobs_started']==0 and p['payload_boundary']['scientific_payload_IO'] is False and p['payload_boundary']['science_payload_hashing'] is False,'boundary'); ok(p['final48_completion']['accepted_actual_product_count']==48 and p['final48_completion']['pending_primary_count']==0,'final completion')
 for name,rr in p['authoritative_sources'].items():
  ref(rr,name); q=Path(rr['path']); ok(q.is_file() and q.suffix.lower()=='.json' and dg(q)==rr['sha256'],name+' external')
 base=Path(p['authoritative_sources']['fresh224_base_products']['path']); base_d=load(base); ok(base_d['accepted_actual_product_count']==47 and [r for r in products['products'] if r.get('physical_case_id')!=PHYS]==base_d['products'],'fresh224 first47 immutable')
 ok(p['root1330_membership']==products['membership'],'membership provenance'); final=p['final_primary_roles']; ok(final['native_canonical_scope_sha256']==CAN and final['typed_xmf_legacy_scope_sha256']==LEG and final['scope_equality_claimed'] is False,'roles')
def validate_adopt(a):
 ok(a['schema']=='ds02.f5.fresh226.root1436-final48-adoption.v1' and a['source_only'] is True,'adoption'); ok(a['final48']=={'accepted_actual_product_count':48,'registered_final48_count':48,'pending_primary_count':0,'case_credit':0,'Q_N':0,'Q_E':0},'adoption final')
 for group in [a['root1436'], {'base':a['base_fresh224']}]:
  for k,v in group.items(): ref(v,'adoption '+k)
 x=a['actual_primary']; ok(x['physical_case_id']==PHYS and x['delivery_order']==28 and x['native_canonical_scope_sha256']==CAN and x['typed_xmf_legacy_scope_sha256']==LEG and x['scope_equality_claimed'] is False,'adoption row')
 ok(x['actual_native_XMF_plan_field_namespaces']['native']['source_plan_condition_sha256']['present'] is False and x['actual_native_XMF_plan_field_namespaces']['XMF']['source_plan_physical_condition_sha256']['present'] is False,'adoption masks')
def main():
 validate_manifest(); products=load(PRODUCTS); prov=load(PROV); adopt=load(ADOPT); validate_products(products); validate_prov(prov,products); validate_adopt(adopt)
 for p in [PRODUCTS,PROV,ADOPT]: ok(not PAYLOAD_RE.search(p.read_text()),'payload suffix in '+p.name)
 print('fresh226 validation PASS: 48 actual primary products, pending=0, metadata-only')
 print('package='+str(PACKAGE))
if __name__=='__main__':
 try: main()
 except AssertionError as e: print('fresh226 validation FAIL:',e,file=sys.stderr); raise
