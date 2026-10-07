from pathlib import Path
import json,hashlib,subprocess,copy,datetime,collections,os,math,re,xml.etree.ElementTree as ET
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');root=lambda n:next(H.glob(f'root*_{n:03d}'))
def load(p):return json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix.lower() in {'.json','.py','.md','.xml','.xmf'};return hashlib.sha256(p.read_bytes()).hexdigest()
def ref(p):return {'path':str(p),'sha256':sha(p)}
def put(p,j):
 with Path(p).open('x') as f:json.dump(j,f,ensure_ascii=False,indent=2);f.write('\n')
cpfile=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_315.json';cp=load(cpfile);assert cp['checkpoint']==315 and cp['stage1_visual_accepted_complete_independent_cases']==len(cp['accepted_decisions'])==sum(cp['accepted_per_family'].values())==327
F=root(1101);pre=F/'actual1075-full836-XMF-and-producer-typed-independent-review.json';z=load(pre)
for e in z.values():
 if isinstance(e,dict) and 'path' in e and 'sha256' in e:assert sha(e['path'])==e['sha256']
q=load(F/'enabled-full836-render-request.json');w=load(F/'enabled-render-wrapper.json');cid=q['case_id'];pid=q['physical_case_id'];s={'native':z['actual_native_receipt'],'typed':z['actual_typed_receipt'],'xmf':z['actual_XMF_receipt']};receipts={}
for key,e in s.items():
 rr=load(e['path']);assert rr['schema']=='ds02.execution-receipt.v1' and (rr['status'],rr['returncode'])==('completed',0) and rr['request']['case_id']==cid;receipts[key]=rr
nq=receipts['native']['request'];t=load(z['actual_typed_report']['path']);x=load(z['actual_XMF_manifest']['path']);o=load(t['source_provenance']['owner_metadata']['path']);canonical=nq['physical_condition_sha256'];assert canonical=='6785314266d78e2247839c32a986838025663f371a65081ce5d42dc38eb80cac'
assert canonical==t['hash_scopes']['physical_condition_sha256']==x['physical_condition_sha256']==o['physical_condition_sha256'];assert t['hash_scopes']['physical_condition']['schema']=='ds-data-02.physical-binding.v1' and o['physical_binding']==nq['physical_binding']==t['hash_scopes']['physical_condition'];assert pid==nq['physical_case_id']==o['physical_case_id']==x['physical_case_id']==t['hash_scopes']['physical_condition']['physical_case_id']
assert (cid,pid)==('F3_STAGE1_DP006_P1200_AY0390','F3_TWOAXIS_P1200_AY0390_STAGE1_FIRST48_PITCH_VARIANT') and nq['nominal_pitch_multiplier']==1.2 and nq['transverse_amplitude_m_s2']==.39
mask={ns:{k:{'present':k in obj,'value':obj.get(k)} for k in ['source_plan_condition_sha256','source_plan_physical_condition_sha256']} for ns,obj in [('native',nq),('XMF',x)]};assert all(not e['present'] and e['value'] is None for e in mask['native'].values());assert mask['XMF']=={'source_plan_condition_sha256':{'present':True,'value':'7560a18fa29742681ee567b06567ed4052da8ceb138b601e94b5223df22660f5'},'source_plan_physical_condition_sha256':{'present':False,'value':None}}
assert w['expected_frames']==t['frames']==x['frames']==836 and w['expected_particles']==t['particles']==x['particles']==179208 and w['expected_contact_sheets']==35 and w['cpu_threads']==w['declared_cpu_cores']==24 and w['environment_threads']==2 and w['global_renderer_cap']==2 and w['home_free_floor_bytes']==500*2**30
assert t['conversion_status']=='completed' and t['solver_dimension']['solver_dimension']==x['dimension']==3 and t['typed_identity']['key']=='(Zone,Idp)' and t['typed_identity']['initial_exclusion_ledger']['count']==0 and t['lifecycle']['introduced_ids']=='rejected' and t['partvtk_validation']['all_passed'] and all(f['passed'] and f['identity_type_mk_exact'] for f in t['partvtk_validation']['frames'])
fs=t['lifecycle']['frame_summary'];times=x['actual_time_s'];grids=ET.parse(z['actual_XMF_XML']['path']).findall('.//Grid[@GridType="Uniform"]');assert len(fs)==len(times)==len(grids)==836 and times==[f['time'] for f in fs]==[float(g.find('Time').get('Value')) for g in grids] and [times[0],times[-1]]==[0,8.350008849684302] and all(math.isfinite(v) for v in times) and all(a<b for a,b in zip(times,times[1:]))
assert x['fields']['position']['shape']==x['fields']['velocity']['shape']==[836,179208,3] and x['xdmf_sha256']==z['actual_XMF_XML']['sha256'] and t['output_sha256']==x['source_h5_sha256']
for i,(f,g) in enumerate(zip(fs,grids)):
 assert f['frame']==i and f['active_particles']==179208 and f['missing_particles']==0 and f['type_counts']=={'0':111708,'1':0,'2':0,'3':67500};assert g.find('Geometry').get('GeometryType')=='XYZ' and g.find('Geometry/DataItem').get('Dimensions')=='179208 3';v=next(v for v in g.findall('Attribute') if v.get('Name').lower()=='velocity');assert v.get('AttributeType')=='Vector' and v.find('DataItem').get('Dimensions')=='179208 3'
refs={}
for k in ['solver_receipt','gencase_receipt','generated_xml','owner_metadata']:
 e=t['source_provenance'][k];assert sha(e['path'])==e['sha256'];refs[k]=e
assert refs['solver_receipt']==s['native'];gc=load(refs['gencase_receipt']['path']);assert gc['schema']=='ds02.execution-receipt.v1' and (gc['status'],gc['returncode'])==('completed',0)
prep=o['root704_preparation_provenance'];assert sha(prep['original_report_path'])==prep['original_report_sha256'];prepared=load(prep['original_report_path']);assert prepared['xml_byte_identical_to_baseline'] and prepared['initial_bi4_byte_identical_to_baseline'] and prepared['physical_condition_sha256']==canonical and prepared['forcing_transform']['status']=='success' and prepared['forcing_transform']['source_sha256_before']==prepared['forcing_transform']['source_sha256_after'];e=nq['actual_preparation_receipt'];assert sha(e['path'])==e['sha256'];pr=load(e['path']);assert pr['schema']=='ds02.execution-receipt.v1' and (pr['status'],pr['returncode'])==('completed',0);refs['actual_preparation_receipt']=e;refs['actual_preparation_report']=ref(prep['original_report_path'])
qr=nq['genuine_parent_initial_QA'];assert sha(qr['path'])==qr['sha256'];qa=load(qr['path']);qarp=Path(qr['path']).parent/'execution-receipt.json';qar=load(qarp);assert qar['schema']=='ds02.execution-receipt.v1' and (qar['status'],qar['returncode'])==('completed',0);qa0=next(v for v in qa['cases'] if v['role']=='twoaxis_dp006');assert qa0['passed'] and qa0['actual_3d'] and qa0['native_particles']==179208 and qa0['native_fixed']==111708 and qa0['native_fluid']==67500
refs['genuine_parent_initial_QA_report']=qr;refs['genuine_parent_initial_QA_receipt']=ref(qarp)
for k in ['forcing','generated_xml','initial_bi4']:
 e=o['producer_attested_inputs'][k];assert receipts['native']['input_hashes_at_launch'][e['path']]==receipts['native']['input_hashes_after_run'][e['path']]==e['sha256']
inputs=o['producer_attested_inputs'];assert qa0['generated_xml_sha256']==inputs['generated_xml']['sha256']==sha(inputs['generated_xml']['path']) and qa0['native_initial_BI4_sha256']==inputs['initial_bi4']['sha256'];h5=t['output_hdf5'];assert receipts['xmf']['input_hashes_at_launch'][h5]==receipts['xmf']['input_hashes_after_run'][h5]==t['output_sha256']
assert sorted(p.name for p in Path(t['source_provenance']['data_root']).glob('Part_*.bi4') if re.fullmatch(r'Part_\d{4,}\.bi4',p.name))==[f'Part_{i:04d}.bi4' for i in range(836)]
front=[]
for original,pidn,start in [(1101,202633,'210026020')]:
 p=Path('/proc')/str(pidn);terminal=root(original)/'controller-result.json';obs=None
 if p.exists():
  st=(p/'stat').read_text().rsplit(')',1)[1].split();args=(p/'cmdline').read_bytes().split(b'\0');assert st[19]==start and any(str(root(original)).encode() in v for v in args);obs={'pid':pidn,'startticks':start,'state':st[0],'original_registered_command_verified':True}
 assert obs is not None or terminal.exists();front.append({'original':original,'same_live_launch':obs,'actual_terminal':ref(terminal) if terminal.exists() else None,'no_restart':True})
for k,p in [('runtime_v2_sha256',L/'scripts/ds_data02_runtime_v2.py'),('strict_dispatch_sha256',L/'scripts/ds_data02_strict_dispatch_v1.py'),('Root142_launch_sha256',root(142)/'launch.py')]:assert sha(p)==cp['unmodified_guards'][k]
raw=(D/'runtime/resource-ledger.json').read_bytes();ld=json.loads(raw);ct=collections.Counter(a['kind'] for a in ld['attempts']);gpu=sum(a.get('gpu_seconds',0) for a in ld['charges'])/3600;cpu=sum(a.get('cpu_core_seconds',0) for a in ld['charges'])/3600;st=os.statvfs('/home/jade');free=st.f_bavail*st.f_frsize/2**30;now=datetime.datetime.now(datetime.timezone.utc);assert free>=500 and gpu<=512 and cpu<=3840 and ct['qualification']<=1024 and ct['production']<=720 and now<datetime.datetime.fromisoformat(cp['deadline_utc'])
