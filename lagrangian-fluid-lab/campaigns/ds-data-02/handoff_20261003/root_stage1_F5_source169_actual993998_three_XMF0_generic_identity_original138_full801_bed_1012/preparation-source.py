from pathlib import Path
import json,hashlib,subprocess,runpy,sys,io,contextlib,copy,xml.etree.ElementTree as ET
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';W=Path('/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics');D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');root=lambda n:next(H.glob(f'root*_{n:03d}'));load=lambda p:json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix.lower() not in {'.h5','.bi4','.dat','.csv','.vtk','.vtu','.npy','.npz'};return hashlib.sha256(p.read_bytes()).hexdigest()
ref=lambda p:{'path':str(p),'sha256':sha(p)}
def put(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
prefix='lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_169_f5_full48_authoritative_census_v1';commit='b37a66c7316ed985f6222f292aeaadafd6b0b77b';names=subprocess.check_output(['git','ls-tree','-r','--name-only',commit,'--',prefix],cwd=W,text=True).splitlines();assert len(names)==13;adopted=[]
for name in names:
 raw=subprocess.check_output(['git','show',f'{commit}:{name}'],cwd=W);assert raw==(W/name).read_bytes();p=R/name;assert not p.exists() or p.read_bytes()==raw;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw);adopted.append(ref(p))
P=R/prefix;O=H/'root_stage1_F5_source169_actual993998_three_XMF0_generic_identity_original138_full801_bed_1012';O.mkdir(exist_ok=True);assert not (O/'controller-config.json').exists();(O/'bindings').mkdir(exist_ok=True);(O/'requests').mkdir(exist_ok=True)
vld=P/'scripts/validate_fresh169.py';v=runpy.run_path(str(vld));report=P/'metadata/fresh169-validator-report.json';before=ref(report);write=Path.write_text
def redirected(path,data,*a,**kw):return write(O/'actual-source169-original-validator-output.json' if path==report else path,data,*a,**kw)
try:
 Path.write_text=redirected
 with contextlib.redirect_stdout(io.StringIO()):v['validate']()
finally:Path.write_text=write
assert ref(report)==before
for row in load(P/'manifest.json')['files']:assert (P/row['path']).stat().st_size==row['bytes'] and sha(P/row['path'])==row['sha256']
first=P/'bindings/M086_T095-root993-original138-bed-binding.json';original_b=load(first);oldadapter=Path(original_b['identity_adapter']['adapter_worker_path']);api161=runpy.run_path(str(oldadapter));error=None
try:api161['validate_binding'](first)
except ValueError as e:error=str(e)
assert error=='fresh138 binding schema mismatch'
put(O/'actual-source169-original161-metadata-rejection.json',{'source_binding':ref(first),'original_adapter':ref(oldadapter),'actual_metadata_error':error,'additional_source_inspection_findings':['Original161 adapter statically binds M086T085, not new cases; original138 expects fresh138 schema.','Nested physical_condition_hash_semantics copied from earlier case and disagree with actual169 top-level case producer scopes.'],'no_scientific_process_started':True,'no_failed_scientific_attempt_or_receipt_claimed':True,'repair_number':1,'source_bytes_preserved':True})
worker=O/'identity-bound-original138-bed.py';worker.write_text('''from pathlib import Path
import json,hashlib,importlib.util,argparse
BAD={'.h5','.hdf5','.bi4','.csv','.dat','.vtk','.vtu','.npy','.npz'}
ORIGINAL_SHA='89be048da1df6bae49627308edb35a8a1936bc0888259cb5ab3d195307b550e2'
# Only schema/identity provenance and actual metadata-backed representations
# change; scientific inputs, geometry, thresholds and full-time contract stay exact.
CHANGES={'schema','identity_adapter','physical_condition_hash_semantics','actual_counts','initial_qa_output_root','initial_qa_report','initial_qa_report_sha256','xmf_manifest','xmf_manifest_sha256','xdmf','xdmf_sha256','xmf_receipt','xmf_receipt_sha256','xmf_attempt_id','root_original_source169_binding','root_metadata_representation_changes'}
def sha(p):
 p=Path(p);assert p.suffix.lower() not in BAD;return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p):return json.loads(Path(p).read_text())
def prepare(bp):
 b=load(bp);source=b['root_original_source169_binding'];assert sha(source['path'])==source['sha256'];old=load(source['path'])
 assert {k:v for k,v in b.items() if k not in CHANGES}=={k:v for k,v in old.items() if k not in CHANGES}
 a=b['identity_adapter'];assert a['schema']=='ds02.f5.root1012.original138.generic-case-identity.v1' and sha(a['worker_path'])==a['worker_sha256']==ORIGINAL_SHA
 assert b['case_id']==b['producer_case_id']==old['case_id'] and b['physical_case_id']==old['physical_case_id']
 for role in ['gencase_receipt','initial_qa_receipt','full_native_receipt','full_typed_receipt','xmf_receipt']:
  r=load(b[role]);assert (r['status'],r['returncode'])==('completed',0) and r['request']['case_id']==b['case_id']
 t=load(b['full_typed_conversion_report']);x=load(b['xmf_manifest']);assert x['physical_case_id']==t['hash_scopes']['physical_condition']['physical_case_id']==b['physical_case_id']
 assert b['trajectory_h5_sha256']==t['output_sha256']==x['source_h5_sha256'] and b['trajectory_h5']==t['output_hdf5']
 assert b['physical_condition_sha256']==x['canonical_physical_condition_sha256']==x['physical_condition_sha256']
 assert b['source_h5_physical_condition_sha256']==t['hash_scopes']['physical_condition_sha256']==x['source_h5_physical_condition_sha256']
 spec=importlib.util.spec_from_file_location('root1012_unchanged_original138',a['worker_path']);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 assert m.CASE_ID=='F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1';m.CASE_ID=b['case_id']
 proof=m._verify_bound_metadata(b) # unchanged original gate; real 801 filenames
 return m,b,proof
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--binding',type=Path,required=True);ap.add_argument('--trajectory-h5',type=Path,required=True);ap.add_argument('--xdmf',type=Path,required=True);ap.add_argument('--output-dir',type=Path,required=True);a=ap.parse_args();m,b,proof=prepare(a.binding)
 assert str(a.trajectory_h5)==b['trajectory_h5'] and str(a.xdmf)==b['xdmf']
 return m.main(['--binding',str(a.binding),'--trajectory-h5',str(a.trajectory_h5),'--xdmf',str(a.xdmf),'--output-dir',str(a.output_dir)])
if __name__=='__main__':raise SystemExit(main())
''')
controller=O/'batch-bed-controller.py';controller.write_text('''from pathlib import Path
import json,hashlib,runpy,time
O=Path(__file__).parent;c=json.loads((O/'controller-config.json').read_text());assert hashlib.sha256(Path(c['fair_dispatch']['path']).read_bytes()).hexdigest()==c['fair_dispatch']['sha256'];dispatch=runpy.run_path(c['fair_dispatch']['path'])['dispatch'];results=[]
for qp in c['requests']:
 assert hashlib.sha256(Path(qp).read_bytes()).hexdigest()==c['request_sha256'][qp];q=json.loads(Path(qp).read_text());r=dispatch(qp,serial_conversion=True);rp=Path(q['attempt_root'])/'execution-receipt.json';a=json.loads(rp.read_text()) if rp.exists() else {};report=Path(q['attempt_root'])/'audit-output/c082s1-full-event-bed-footprint-audit.json';b=json.loads(report.read_text()) if report.exists() else {}
 actual0=r.returncode==0 and a.get('status')=='completed' and a.get('returncode')==0 and b.get('case_id')==q['case_id'] and b.get('physical_case_id')==q['physical_case_id']
 z={'tag':q['tag'],'case_id':q['case_id'],'request':qp,'actual_receipt':str(rp),'actual_report':str(report),'status':a.get('status'),'returncode':a.get('returncode'),'launcher_returncode':r.returncode,'actual_full801_bed_worker_output0':actual0,'physical_penetration_pass_not_inferred_from_exitcode':True,'stdout_tail':r.stdout[-1200:],'stderr_tail':r.stderr[-1200:],'case_credit':0};results.append(z);(O/'actual-progress.json').write_text(json.dumps({'results':results,'not_submitted':len(c['requests'])-len(results),'case_credit':0},indent=2)+'\n')
 if not actual0:raise SystemExit(r.returncode or 1)
 time.sleep(4)
(O/'controller-result.json').write_text(json.dumps({'status':'completed','returncode':0,'actual_worker_completed0':len(results),'case_credit':0},indent=2)+'\n')
''')
prepared=[];proofs=[];fair=root(928)/'fair_CPU_dispatch.py';api=runpy.run_path(str(worker));base=load(root(971)/'enabled-bed-request.json')
for tag in ['M086_T095','M088_T085','M088_T095']:
 sb=P/f'bindings/{tag}-root993-original138-bed-binding.json';sq=P/f'requests/{tag}-root993-original138-bed-request.json';b=load(sb);q=load(sq);xr=next(load(p) for p in (root(993)/'requests').glob('*.json') if load(p)['case_id']==b['case_id']);xp=Path(xr['attempt_root'])/'xmf/manifest.json';x=load(xp);rp=Path(xr['attempt_root'])/'execution-receipt.json';assert (load(rp)['status'],load(rp)['returncode'])==('completed',0);xml=Path(x['xdmf']);t=load(b['full_typed_conversion_report']);tq=load(b['typed_request']);own=load(tq['owner_metadata']);definition=Path(own['source_definition']);assert sha(definition)==own['source_definition_sha256']==b['source_plan_physical_condition_sha256']
 assert x['physical_condition_sha256']==b['physical_condition_sha256'] and x['source_h5_physical_condition_sha256']==b['source_h5_physical_condition_sha256'] and x['source_h5_sha256']==b['trajectory_h5_sha256']==t['output_sha256'] and x['source_plan_physical_condition_sha256']==tq['source_plan_physical_condition_sha256']
 assert x['frames']==t['frames']==801 and x['particles']==t['particles']==194427 and sha(xml)==x['xdmf_sha256']
 fs=t['lifecycle']['frame_summary'];grids=ET.parse(xml).findall('.//Grid[@GridType="Uniform"]');assert x['actual_time_s']==[a['time'] for a in fs]==[float(g.find('Time').get('Value')) for g in grids] and len(grids)==801 and fs[-1]['time']>=16
 assert all(f['missing_particles']==0 and f['active_particles']==194427 for f in fs)
 actualqa=Path(tq['actual_initial_qa_report']);assert sha(actualqa)==tq['actual_initial_qa_report_sha256'];trmeta=load(b['full_typed_receipt']);assert trmeta['input_hashes_at_launch'][str(actualqa)]==trmeta['input_hashes_after_run'][str(actualqa)]==sha(actualqa)
 b.update(schema='ds02.f5.c082s1.full-event-bed-audit-binding.fresh138.v1',initial_qa_report=str(actualqa),initial_qa_report_sha256=sha(actualqa),actual_counts=load(actualqa)['actual_counts'],initial_qa_output_root=load(b['initial_qa_receipt'])['output_root'],xmf_manifest=str(xp),xmf_manifest_sha256=sha(xp),xdmf=str(xml),xdmf_sha256=sha(xml),xmf_receipt=str(rp),xmf_receipt_sha256=sha(rp),xmf_attempt_id=xr['attempt_id'],root_original_source169_binding=ref(sb),root_metadata_representation_changes=['original138 required schema','generic actual producer case identity','current nested canonical/legacy scope representations','real XMF references if previously future/null','QA counts/output-root exact actual representations'])
 original=Path(b['identity_adapter']['original_worker_path']);assert sha(original)=='89be048da1df6bae49627308edb35a8a1936bc0888259cb5ab3d195307b550e2';b['identity_adapter']={'schema':'ds02.f5.root1012.original138.generic-case-identity.v1','worker_path':str(original),'worker_sha256':sha(original),'loaded_original_CASE_ID_only_changed':True,'scientific_logic_thresholds_geometry_unchanged':True}
 b['physical_condition_hash_semantics']={'canonical_owner_sha256':b['physical_condition_sha256'],'source_h5_sha256':b['source_h5_physical_condition_sha256'],'source_h5_scope_schema':'legacy-owner-scope.v0','source_h5_scope_status':'legacy_incomplete; no cross-resolution physical claim','source_plan_definition_XML_SHA':b['source_plan_physical_condition_sha256'],'definition_XML':str(definition),'actual_XMF_plan_physical_condition_sha256':x['source_plan_physical_condition_sha256'],'different_schema_roles_are_not_equated':True,'cross_resolution_claim':False}
 bp=O/'bindings'/f'{tag}-original138-real-producer-binding.json';put(bp,b);m,checked,gateproof=api['prepare'](bp);gp=O/f'{tag}-actual-original138-metadata-gate.json';put(gp,gateproof)
 md=q['input_sha256'].copy()
 for p,h in md.items():assert Path(p).is_file() and sha(p)==h
 for p in [worker,controller,fair,bp,sb,sq,original,gp,xp,xml,rp,definition,Path(tq['owner_metadata']),actualqa,L/'scripts/ds_data02_runtime_v2.py',L/'scripts/ds_data02_strict_dispatch_v1.py',root(142)/'launch.py',root(142)/'root_home_floor_inventory_policy.py',root(64)/'resource-window-approval.json']:md[str(p)]=sha(p)
 tr=load(b['full_typed_receipt']);py=str(L/'.venv/bin/python');md[py]=tr['input_hashes_at_launch'][str(Path(py).resolve())];assert md[py]==tr['input_hashes_after_run'][str(Path(py).resolve())];md[b['trajectory_h5']]=t['output_sha256']
 aid=f'root-stage1-f5-{tag.lower()}-actual993998-full801-original138-generic-identity-bed-root1012';ar=D/'families/F5'/b['case_id']/aid;assert not ar.exists()
 q.update({k:base[k] for k in ['root_dataset_inventory_profile','root_inventory_policy_sha256','root_actual_launch_source','root_actual_launch_source_sha256','science_input_policy','environment_policy']});q.update(attempt_id=aid,attempt_root=str(ar),binding=str(bp),binding_sha256=sha(bp),command=[py,str(worker),'--binding',str(bp),'--trajectory-h5',b['trajectory_h5'],'--xdmf',b['xdmf'],'--output-dir','{attempt_root}/audit-output'],input_files=sorted(md),input_sha256=md,worktree_root=str(R),disabled=False,source_only=False,launch=True,launch_allowed=True,execution_allowed=True,root_review_required=False,full801_authorized=True,case_credit=0)
 qp=O/'requests'/f'{tag}-enabled-bed-request.json';put(qp,q);prepared.append(str(qp));proofs.append({'tag':tag,'enabled_binding':ref(bp),'actual_original138_all_metadata_checks_pass':ref(gp),'source_definition_XML_role_digest':ref(definition),'actual_XMF_plan_condition_role':x['source_plan_physical_condition_sha256'],'all801_N3_typed_XMF_actual_times_and_UIDs_verified':True,'source_science_and_thresholds_unchanged':True,'scientific_payload_IO':False})
put(O/'controller-config.json',{'requests':prepared,'request_sha256':{p:sha(p) for p in prepared},'fair_dispatch':ref(fair),'effective_shared_serial_conversion_concurrency':1,'case_credit':0});put(O/'source169-adoption-real-original138-generic-identity-repair1-review.json',{'source_commit':commit,'adopted_files':adopted,'source_validator_report_preserved':before,'original_metadata_rejection_preserved':ref(O/'actual-source169-original161-metadata-rejection.json'),'cases':proofs,'original138_kernel_hash_unchanged':True,'schema_and_identity_metadata_adapter_only':True,'future_bed_hashes_null':True,'science_payload_IO':False,'q_n_granted':False,'case_credit':0});(O/'preparation-source.py').write_bytes(Path(__file__).read_bytes());paths=[str(Path(p['path']).relative_to(R)) for p in adopted]+[str(p.relative_to(R)) for p in O.rglob('*') if p.is_file()];subprocess.run(['git','add','--',*paths],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','ds02: preserve source169 metadata refusal and bind three real cases to unchanged138 bed kernel','--',*paths],cwd=R,check=True);print({'root':str(O),'registered':len(prepared),'actual_original138_metadata_gates':3,'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()})
