#!/usr/bin/env python3
"""Bounded source/metadata preflight for fresh102; never reads science payloads."""
from __future__ import annotations
import hashlib, importlib.util, json, sys
from pathlib import Path

PKG=Path(__file__).resolve().parents[1]
CONVERTER=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_direct_convert.py')
BASE_MOTION=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050/root-compact-equilibrium-runup_coarse-clip-direction-fix-gencase-050/prepared/assets/f5_compact_packet_motion.dat')
BASE_MOTION_SHA='51e197f0831915a73534c619704658b06812c9d52c38c470ab4cbb8d59f5614a'
CONVERTER_SHA='8ec204edb5ac20f2d83e2b9a3b5e70eb45cf1104fe0ee4bd8c3413a241c10ccd'
ROOT230_POLICY_SHA='c9103e306f87bb5af871c5de28d9939aa05f0c95c72e1630778f4bcf50e91ab5'
ROOT230_LAUNCH_SHA='7f703fb94e17c2e2800873f4fcc021f9cd5f8201076afd8e10e3bc6a2d03396e'
SCIENCE={'.dat','.bi4','.h5','.hdf5','.csv','.vtk','.vtu','.xmf','.xdmf'}
FORBIDDEN={'dp_m','resolution','particle_counts','particle_count','expected_particles','expected_fluid_particles','save_interval_s','solver_timestep_s','time_out_s','tout_s','cfl','lattice_residual','numerical_precision'}

def load(p): return json.loads(Path(p).read_text())
def sha(p):
 p=Path(p)
 if p.suffix.lower() in SCIENCE: raise RuntimeError('science payload hashing forbidden: '+str(p))
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def walk_keys(v,where='binding'):
 found=[]
 if isinstance(v,dict):
  for k,x in v.items():
   if k.lower() in FORBIDDEN: found.append(f'{where}.{k}')
   found.extend(walk_keys(x,f'{where}.{k}'))
 elif isinstance(v,list):
  for i,x in enumerate(v): found.extend(walk_keys(x,f'{where}[{i}]'))
 return found
def import_converter():
 spec=importlib.util.spec_from_file_location('ds_data02_direct_convert_fresh102_preflight',CONVERTER)
 if spec is None or spec.loader is None: raise RuntimeError('converter import failed')
 mod=importlib.util.module_from_spec(spec); sys.modules[spec.name]=mod; spec.loader.exec_module(mod); return mod
def ensure(cond,msg):
 if not cond: raise AssertionError(msg)
def main():
 ensure(sha(CONVERTER)==CONVERTER_SHA,'converter source SHA drift')
 mod=import_converter(); reports={}; bindings={}
 for cid in ('A080','A120'):
  bpath=PKG/'bindings'/f'{cid}-physical-binding.json'; rpath=PKG/'metadata'/f'{cid}-explicit-physical-binding-report.json'
  b=load(bpath); r=load(rpath); scoped=mod._physical_condition_scope({'physical_binding':b}); validated=mod._validate_physical_binding(b)
  ensure(scoped==validated,f'{cid}: converter scope mismatch'); h=mod.canonical_hash(scoped); ensure(h==r['canonical_physical_binding_sha256'],f'{cid}: scope hash mismatch')
  bad=walk_keys(b)
  ensure(not bad,f'{cid}: resolution/count field in physical scope {bad}')
  ensure(b['schema']=='ds-data-02.physical-binding.v1',f'{cid}: schema')
  ensure(b['physical_case_id']==load(PKG/'inputs'/f'{cid}-owner.json')['physical_case_id'],f'{cid}: physical owner mismatch')
  bindings[cid]=h
 # Static request/hash contract; science suffixes are only placeholders or producer-declared base DAT.
 reqs=sorted((PKG/'requests').glob('*.json')); ensure(len(reqs)==10,f'expected 10 requests, got {len(reqs)}')
 seen={}
 for p in reqs:
  q=load(p); ensure(q.get('schema')=='ds02.runner-request.v2',f'{p.name}: schema'); ensure(q.get('disabled') is True,f'{p.name}: not disabled'); ensure(q.get('launch') is False and q.get('launch_allowed') is False and q.get('execution_allowed') is False,f'{p.name}: execution enabled'); ensure(q.get('solver_allowed') is False and q.get('conversion_allowed') is False,f'{p.name}: solver/conversion policy'); ensure(q.get('arrays_allowed') is False and q.get('array_edit_allowed') is False,f'{p.name}: array policy'); ensure(q.get('independent_case_count_increment')==0,f'{p.name}: case increment'); ensure(q.get('full801_authorized') is False,f'{p.name}: full801')
  cid='A080' if 'A080' in p.name else 'A120'; ensure(q.get('physical_condition_sha256')==bindings[cid],f'{p.name}: binding hash')
  if q.get('kind')=='qualification': ensure(q.get('cpu_task_kind')=='solver',f'{p.name}: native task kind'); ensure(q.get('root_inventory_policy_source_sha256')==ROOT230_POLICY_SHA,f'{p.name}: native Root230 policy'); ensure(q.get('root_actual_launch_source_sha256')==ROOT230_LAUNCH_SHA,f'{p.name}: native Root230 launch'); ensure(q.get('estimated_peak_gpu_mib')==4096,f'{p.name}: GPU reservation')
  else: ensure(q.get('kind')=='cpu',f'{p.name}: CPU kind'); ensure(q.get('cpu_task_kind') in {'audit','gencase'},f'{p.name}: CPU task kind')
  seen.setdefault(cid,[]).append(q['attempt_id'])
  files=q.get('input_files',[]); hs=q.get('input_sha256',{}); ensure(set(files)==set(hs),f'{p.name}: input hash key closure')
  for s,val in hs.items():
   path=Path(s)
   if s.startswith('<root-bind:') or not path.exists(): ensure(val is None,f'{p.name}: unresolved input must be null {s}'); continue
   if path==BASE_MOTION: ensure(val==BASE_MOTION_SHA,f'{p.name}: base DAT must use registered producer hash'); continue
   if path.suffix.lower() in SCIENCE: ensure(val is None,f'{p.name}: future science input hash must be null'); continue
   ensure(val==sha(path),f'{p.name}: static input SHA mismatch {s}')
  for k,v in q.get('future_output_hashes',{}).items(): ensure(v is None,f'{p.name}: future hash {k} is non-null')
 ensure(all(len(v)==5 for v in seen.values()),'stage count')
 # Binding request files themselves must carry the current binding hash.
 for p in reqs:
  q=load(p)
  if 'binding_sha256' in q:
   bp=Path(q['binding']); ensure(bp.is_file(),f'{p.name}: binding missing'); ensure(q['binding_sha256']==sha(bp),f'{p.name}: binding SHA drift')
 # Candidate future counts are null everywhere; baseline provenance remains outside requests.
 for cid in ('A080','A120'):
  for p in reqs:
   if cid not in p.name: continue
   q=load(p)
   if 'actual_counts' in q: ensure(q['actual_counts'] is None,f'{p.name}: candidate actual counts guessed')
   for k in ('expected_particles','expected_fixed_particles','expected_moving_particles','expected_fluid_particles','expected_floating_particles','expected_particle_axis'):
    if k in q: ensure(q[k] is None,f'{p.name}: future count {k} guessed')
 dump={'schema':'ds02.f5.c082s1.fresh102-preflight-report.v1','status':'passed_metadata_only','source_only':True,'science_arrays_read':False,'science_arrays_hashed':False,'jobs_started':False,'shared_state_modified':False,'converter_scope_validation':{'converter_source_sha256':CONVERTER_SHA,'A080':bindings['A080'],'A120':bindings['A120'],'schema':'ds-data-02.physical-binding.v1','hashes_distinct':bindings['A080']!=bindings['A120']},'request_count':len(reqs),'request_attempts':seen,'future_candidate_counts_and_hashes_null':True,'full801_enabled':False,'independent_case_count_increment':0,'root230_gpu_protection':{'policy_sha256':ROOT230_POLICY_SHA,'launch_sha256':ROOT230_LAUNCH_SHA,'qualification_gpu_mib':4096,'launch_owner':'root'}}
 (PKG/'metadata/fresh102-preflight-report.json').write_text(json.dumps(dump,indent=2,sort_keys=True)+'\n')
 print(json.dumps(dump,sort_keys=True))
if __name__=='__main__': main()
