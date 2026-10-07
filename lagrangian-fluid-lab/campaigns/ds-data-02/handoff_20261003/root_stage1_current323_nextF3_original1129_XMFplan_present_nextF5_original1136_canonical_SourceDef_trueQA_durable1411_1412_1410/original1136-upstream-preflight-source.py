from pathlib import Path
import json,hashlib,subprocess,copy,datetime,collections,os,math,xml.etree.ElementTree as ET
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');root=lambda n:next(H.glob(f'root*_{n:03d}'))
def load(p):return json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix.lower() in {'.json','.py','.md','.xml','.xmf'};return hashlib.sha256(p.read_bytes()).hexdigest()
def ref(p):return {'path':str(p),'sha256':sha(p)}
def put(p,j):
 with Path(p).open('x') as f:json.dump(j,f,ensure_ascii=False,indent=2);f.write('\n')
cpfile=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_305.json';cp=load(cpfile);assert cp['checkpoint']==305 and cp['stage1_visual_accepted_complete_independent_cases']==len(cp['accepted_decisions'])==sum(cp['accepted_per_family'].values())==323
F=root(1136);pre=F/'actual-full801-bed-UID-footprint-times-and-scope-independent-review.json';j=load(pre);refs={k:e for k,e in j.items() if isinstance(e,dict) and 'path' in e and 'sha256' in e}
for e in refs.values():assert sha(e['path'])==e['sha256']
t=load(j['actual_typed_report']['path']);x=load(j['actual_XMF_manifest']['path']);native_ref=t['source_provenance']['solver_receipt'];assert sha(native_ref['path'])==native_ref['sha256'];n=load(native_ref['path']);nq=n['request'];bedr=load(j['actual_bed_receipt']['path']);b=load(bedr['request']['binding']);bed=load(j['actual_bed_report']['path']);refs['actual_native_receipt']=native_ref;refs['actual_bed_binding']=ref(bedr['request']['binding']);canonical=nq['physical_condition_sha256'];legacy=t['hash_scopes']['physical_condition_sha256'];sd=b['source_plan_physical_condition_sha256'];assert (canonical,legacy,sd)==('5adae02901dfdd5e70f7de3b62694c5f7f62f5d76ade14b0a8688ae9c2d0d273','04b4720db5456a4e01f5c5cbc3af67d2d1cedb15d784689ed7175c060a959fa8','6a56496593d43b8ca6f1910c3a934202c493db1a071e286f28c10488f38adeb9')
mask={ns:{k:{'present':k in obj,'value':obj.get(k)} for k in ['source_plan_condition_sha256','source_plan_physical_condition_sha256']} for ns,obj in [('native',nq),('XMF',x)]}
for m in mask.values():assert m=={'source_plan_condition_sha256':{'present':False,'value':None},'source_plan_physical_condition_sha256':{'present':True,'value':canonical}}
source_def=ref(b['source_definition']);assert source_def['sha256']==b['source_definition_sha256']==sd==bed['source_plan_physical_condition_sha256'];plan=ref(b['source_plan_file']);assert plan['sha256']==b['source_plan_file_sha256'] and len({canonical,legacy,sd,plan['sha256']})==4
for rr in [n,bedr]:assert rr['input_hashes_at_launch'][plan['path']]==rr['input_hashes_after_run'][plan['path']]==plan['sha256']
q=load(F/'enabled-full801-render-request.json');w=load(F/'enabled-render-wrapper.json');cid=q['case_id'];pid=q['physical_case_id'];assert pid=='F5_COMPACT_RUNUP_RECOVERY_C082S1_M092_T095' and cid=='F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M092_T095_NEXT34'
for k,bkey in [('gencase_receipt','gencase_receipt'),('initial_qa_receipt','initial_qa_receipt'),('initial_qa_report','initial_qa_report'),('generated_xml','canonical_generated_xml')]:
 e=ref(b[bkey]);assert e['sha256']==b[bkey+'_sha256'];refs[k]=e
for k in ['gencase_receipt','initial_qa_receipt','actual_native_receipt','actual_typed_receipt','actual_XMF_receipt','actual_bed_receipt']:
 rr=load(refs[k]['path']);assert rr['schema']=='ds02.execution-receipt.v1' and rr['status']=='completed' and rr['returncode']==0 and rr['request']['case_id']==cid
qa=load(refs['initial_qa_report']['path']);assert qa['all_basic_placement_checks_pass'] and all(qa['checks'].values()) and not qa['numerical_precision_result_accepted'];assert t['source_provenance']['gencase_receipt']==refs['gencase_receipt'] and t['source_provenance']['generated_xml']==refs['generated_xml']
assert w['expected_frames']==t['frames']==x['frames']==len(bed['frame_reports'])==801 and w['expected_particles']==t['particles']==x['particles']==194427 and w['expected_contact_sheets']==34
assert t['conversion_status']=='completed' and t['solver_dimension']['solver_dimension']==3 and t['typed_identity']['key']=='(Zone,Idp)' and t['typed_identity']['initial_exclusion_ledger']['count']==0 and t['lifecycle']['introduced_ids']=='rejected' and t['partvtk_validation']['all_passed'];assert x['fields']['position']['shape']==x['fields']['velocity']['shape']==[801,194427,3]
fs=t['lifecycle']['frame_summary'];times=x['actual_time_s'];xp=Path(x['xdmf']);refs['XMF_XML']=ref(xp);assert refs['XMF_XML']['sha256']==x['xdmf_sha256'];grids=ET.parse(xp).findall('.//Grid[@GridType="Uniform"]');assert len(fs)==len(times)==len(grids)==801 and times==[f['time'] for f in fs]==[f['time_s'] for f in bed['frame_reports']]==[float(g.find('Time').get('Value')) for g in grids];assert [times[0],times[-1]]==[0,16.00014188025401] and all(math.isfinite(v) for v in times) and all(a<b for a,b in zip(times,times[1:]))
for i,(f,bf,g) in enumerate(zip(fs,bed['frame_reports'],grids)):
 assert f['frame']==bf['frame']==i and f['active_particles']==194427 and f['missing_particles']==0 and f['type_counts']=={'0':158559,'1':4210,'2':0,'3':31658}
 assert g.find('Geometry').get('GeometryType')=='XYZ' and g.find('Geometry/DataItem').get('Dimensions')=='194427 3';v=next(z for z in g.findall('Attribute') if z.get('Name')=='velocity');assert v.get('AttributeType')=='Vector' and v.find('DataItem').get('Dimensions')=='194427 3'
 assert bf['initial_fluid_uid_count']==bf['current_valid_type3_fluid_count']==bf['finite_mass_current_fluid_count']==bf['finite_position_current_fluid_count']==31658 and bf['uid_tracking']['missing_initial_uid']['count']==bf['uid_tracking']['unexpected_current_uid']['count']==bf['nonfinite_mass_current_fluid_count']==bf['nonfinite_position_current_fluid_count']==0 and not bf['uid_tracking']['unexplained'];assert bf['bed_domain']['x_outside_exact_profile_domain_count']==bf['bed_domain']['y_outside_actual_bed_footprint_with_x_in_domain_count']==bf['penetration']['depth_unevaluable_current_fluid_count']==0
 for k,th in [('one_dp',.02),('two_dp',.04)]:assert bf['penetration'][k]['threshold_m']==th and bf['penetration'][k]['count']==0 and bf['penetration'][k]['deepest_depth_m'] is None
h5=t['output_hdf5'];assert t['output_sha256']==x['source_h5_sha256']
for k in ['actual_XMF_receipt','actual_bed_receipt']:
 rr=load(refs[k]['path']);assert rr['input_hashes_at_launch'][h5]==rr['input_hashes_after_run'][h5]==t['output_sha256']
pp=Path('/proc/724322');obs=None
if pp.exists():
 st=(pp/'stat').read_text().rsplit(')',1)[1].split();args=(pp/'cmdline').read_bytes().split(b'\0');assert st[19]=='214858903' and str(F/'enabled-render-wrapper.json').encode() in args;obs={'registered_launch_pid':724322,'startticks':'214858903','state':st[0],'original_request_bound_to_actual_cmdline':True,'no_restart':True}
assert obs is not None or (F/'controller-result.json').exists()
for key,p in [('runtime_v2_sha256',L/'scripts/ds_data02_runtime_v2.py'),('strict_dispatch_sha256',L/'scripts/ds_data02_strict_dispatch_v1.py'),('Root142_launch_sha256',root(142)/'launch.py')]:assert sha(p)==cp['unmodified_guards'][key]
raw=(D/'runtime/resource-ledger.json').read_bytes();ld=json.loads(raw);ct=collections.Counter(a['kind'] for a in ld['attempts']);gpu=sum(a.get('gpu_seconds',0) for a in ld['charges'])/3600;cpu=sum(a.get('cpu_core_seconds',0) for a in ld['charges'])/3600;st=os.statvfs('/home/jade');free=st.f_bavail*st.f_frsize/2**30;now=datetime.datetime.now(datetime.timezone.utc);assert free>=500 and gpu<=512 and cpu<=3840 and ct['qualification']<=1024 and ct['production']<=720 and now<datetime.datetime.fromisoformat(cp['deadline_utc'])
