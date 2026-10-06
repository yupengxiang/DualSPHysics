from pathlib import Path
import json,hashlib,subprocess,runpy,datetime,xml.etree.ElementTree as ET
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';W=Path('/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics');D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');root=lambda n:next(H.glob(f'root*_{n:03d}'));load=lambda p:json.loads(Path(p).read_text())
BAD={'.h5','.hdf5','.bi4','.csv','.dat','.vtk','.vtu','.npy','.npz'}
def sha(p):
 p=Path(p);assert p.suffix.lower() not in BAD
 return hashlib.sha256(p.read_bytes()).hexdigest()
ref=lambda p:{'path':str(p),'sha256':sha(p)}
def put(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
prefix='lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_179_f5_original138_bed_and_m090_t095_render_disabled_v1';commit='173988a931d97355c16abf6adba6c0c983ab0d66';names=subprocess.check_output(['git','ls-tree','-r','--name-only',commit,'--',prefix],cwd=W,text=True).splitlines();assert len(names)==24;adopted=[]
for name in names:
 assert Path(name).suffix in {'.json','.py','.md'}
 raw=subprocess.check_output(['git','show',f'{commit}:{name}'],cwd=W);assert raw==(W/name).read_bytes();p=R/name;assert not p.exists() or p.read_bytes()==raw;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw);adopted.append(ref(p))
P=W/prefix;O=H/'root_stage1_source179_five_actual1035_1073_1074_XMF0_full801_original138_identity_adapter_bed_CPU2_1108';assert not O.exists();O.mkdir();(O/'requests').mkdir()
before={name:sha(W/name) for name in names};rv=subprocess.run([str(L/'.venv/bin/python'),'-B',str(P/'scripts/validate_fresh179.py')],capture_output=True,text=True);assert rv.returncode==0 and before=={name:sha(W/name) for name in names}
put(O/'source179-original-validator-preserved-source-proof.json',{'source_validator':ref(P/'scripts/validate_fresh179.py'),'stdout':rv.stdout,'stderr':rv.stderr,'returncode':rv.returncode,'source_bytes_unchanged':True,'science_payload_IO':False})
worker=P/'workers/identity_bound_bed_audit_fresh179.py';api=runpy.run_path(str(worker));original=api['ORIGINAL_WORKER'];assert sha(original)=='89be048da1df6bae49627308edb35a8a1936bc0888259cb5ab3d195307b550e2'
fair=root(928)/'fair_CPU_dispatch.py';assert sha(fair)=='e2796fb88cc989278bcc4d194493f11e5ded7e6d2fb79ef37349d7ae7d8d679f'
controller=O/'batch-bed-controller.py';controller.write_text('''from pathlib import Path
import json,hashlib,runpy,time
O=Path(__file__).parent;c=json.loads((O/'controller-config.json').read_text());assert hashlib.sha256(Path(c['fair_dispatch']['path']).read_bytes()).hexdigest()==c['fair_dispatch']['sha256'];dispatch=runpy.run_path(c['fair_dispatch']['path'])['dispatch'];results=[]
for qp in c['requests']:
 assert hashlib.sha256(Path(qp).read_bytes()).hexdigest()==c['request_sha256'][qp];q=json.loads(Path(qp).read_text());r=dispatch(qp,serial_conversion=True);rp=Path(q['attempt_root'])/'execution-receipt.json';a=json.loads(rp.read_text()) if rp.exists() else {};report=Path(q['attempt_root'])/'audit-output/c082s1-full-event-bed-footprint-audit.json';b=json.loads(report.read_text()) if report.exists() else {};bound=b.get('bound_actual_inputs',{})
 actual0=(r.returncode==0 and a.get('status')=='completed' and a.get('returncode')==0 and b.get('status')=='completed_worker_output_pending_root_review' and bound.get('case_id')==q['case_id'] and bound.get('physical_case_id')==q['physical_case_id'] and bound.get('full_native_solver',{}).get('saved_state_count')==801 and len(b.get('frame_reports',[]))==801)
 z={'tag':q['tag'],'case_id':q['case_id'],'physical_case_id':q['physical_case_id'],'request':qp,'actual_receipt':str(rp),'actual_report':str(report),'status':a.get('status'),'returncode':a.get('returncode'),'launcher_returncode':r.returncode,'actual_full801_bed_worker_output0':actual0,'physical_penetration_pass_not_inferred_from_exitcode':True,'stdout_tail':r.stdout[-1200:],'stderr_tail':r.stderr[-1200:],'case_credit':0};results.append(z);(O/'actual-progress.json').write_text(json.dumps({'results':results,'not_submitted':len(c['requests'])-len(results),'case_credit':0},indent=2)+'\\n')
 if not actual0:
  (O/'controller-result.json').write_text(json.dumps({'status':'stopped_for_primary_failure_classification','failed_tag':q['tag'],'returncode':r.returncode or 1,'not_submitted':len(c['requests'])-len(results),'case_credit':0},indent=2)+'\\n');raise SystemExit(r.returncode or 1)
 time.sleep(4)
(O/'controller-result.json').write_text(json.dumps({'status':'completed','returncode':0,'actual_worker_completed0':len(results),'case_credit':0},indent=2)+'\\n')
''');compile(controller.read_text(),str(controller),'exec')
cp=load(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_167.json');ids={load(p).get('physical_case_id',load(p)['case_id']) for p in cp['accepted_decisions']};requests=[];reviews=[]
for source in sorted((P/'requests').glob('*-original138-bed-request.json')):
 q=load(source);assert q['disabled'] and not q['execution_allowed'];b=load(q['binding']);assert b['physical_case_id'] not in ids
 gate=api['validate_binding'](Path(q['binding']),run_original_metadata_gate=True);gp=O/(b['tag']+'-actual-original138-metadata-gate.json');put(gp,gate)
 t=load(b['full_typed_conversion_report']);x=load(b['xmf_manifest']);xr=load(b['xmf_receipt']);tr=load(b['full_typed_receipt']);n=load(b['full_native_receipt'])
 assert all((r['status'],r['returncode'])==('completed',0) for r in [xr,tr,n]) and n['request']['physical_case_id']==b['physical_case_id']
 assert x['frames']==t['frames']==801 and x['particles']==t['particles']==194427 and x['source_h5_sha256']==t['output_sha256']==b['trajectory_h5_sha256']
 assert x['physical_condition_sha256']==x['canonical_physical_condition_sha256']==n['request']['physical_condition_sha256']==b['physical_condition_sha256']
 assert x['source_h5_physical_condition_sha256']==t['hash_scopes']['physical_condition_sha256']==b['source_h5_physical_condition_sha256']
 assert sha(b['source_definition'])==b['source_plan_physical_condition_sha256'] and x['source_plan_physical_condition_sha256']==load(b['typed_request'])['source_plan_physical_condition_sha256']
 assert x['xdmf_sha256']==sha(b['xdmf']) and xr['input_hashes_at_launch'][b['trajectory_h5']]==xr['input_hashes_after_run'][b['trajectory_h5']]==t['output_sha256']
 fs=t['lifecycle']['frame_summary'];grids=ET.parse(b['xdmf']).findall('.//Grid[@GridType="Uniform"]');times=x['actual_time_s'];assert len(fs)==len(grids)==801 and times==[f['time'] for f in fs]==[float(g.find('Time').get('Value')) for g in grids]
 assert times[0]==0 and times[-1]>=16 and all(a<c for a,c in zip(times,times[1:])) and x['fields']['position']['shape']==x['fields']['velocity']['shape']==[801,194427,3]
 assert all(f['frame']==i and f['active_particles']==194427 and f['missing_particles']==0 for i,f in enumerate(fs))
 assert all(v is None for v in q['future_output_hashes'].values())
 md=q['input_sha256'].copy()
 for p,h in md.items():assert Path(p).is_file() and sha(p)==h
 for p in [source,worker,original,controller,fair,gp,O/'source179-original-validator-preserved-source-proof.json',root(142)/'launch.py',root(142)/'root_home_floor_inventory_policy.py',root(64)/'resource-window-approval.json',L/'scripts/ds_data02_runtime_v2.py',L/'scripts/ds_data02_strict_dispatch_v1.py']:md[str(p)]=sha(p)
 md[b['trajectory_h5']]=t['output_sha256'];py=L/'.venv/bin/python';pysha=tr['input_hashes_at_launch'][str(py.resolve())];assert pysha==tr['input_hashes_after_run'][str(py.resolve())];md[str(py)]=pysha
 aid=f"root-stage1-f5-{b['tag'].lower()}-actual1035-1073-1074-full801-original138-fresh179-bed-root1108";ar=D/'families/F5'/b['case_id']/aid;assert not ar.exists()
 q.update(attempt_id=aid,attempt_root=str(ar),tag=b['tag'],command=[str(py),str(worker),'--binding',q['binding'],'--trajectory-h5',b['trajectory_h5'],'--xdmf',b['xdmf'],'--output-dir','{attempt_root}/audit-output'],input_files=sorted(md),input_sha256=md,worktree_root=str(R),disabled=False,source_only=False,launch=True,launch_allowed=True,execution_allowed=True,root_review_required=False,full801_authorized=True,case_credit=0)
 qp=O/'requests'/(b['tag']+'-enabled-bed-request.json');put(qp,q);requests.append(str(qp));reviews.append({'tag':b['tag'],'source_request':ref(source),'source_binding_kept_disabled_as_immutable_provenance_outer_request_is_authorization':ref(b['binding']),'original138_metadata_gate':ref(gp),'typed_report':ref(b['full_typed_conversion_report']),'XMF_manifest':ref(b['xmf_manifest']),'own_definition_source_plan_SHA':ref(b['source_definition']),'XMF_producer_plan_role':x['source_plan_physical_condition_sha256'],'native_canonical_scope':b['physical_condition_sha256'],'actual_typed_legacy_scope':b['source_h5_physical_condition_sha256'],'all801_UID_N3_times_preserved':True,'main_scientific_payload_IO':False,'future_bed_hashes_null':True,'enabled_request':ref(qp),'case_credit':0})
put(O/'controller-config.json',{'requests':requests,'request_sha256':{p:sha(p) for p in requests},'fair_dispatch':ref(fair),'effective_shared_serial_conversion_concurrency':1,'case_credit':0})
put(O/'source179-five-full801-bed-independent-adoption-review.json',{'source_commit':commit,'adopted_files':adopted,'cases':reviews,'original138_kernel_SHA':sha(original),'source179_identity_adapter_SHA':sha(worker),'original_worker_logic_and_all_scientific_inputs_unchanged':True,'controller_observes_actual_bound_actual_inputs_identity_and801_frame_report_schema':True,'source_metadata_bytes_preserved':True,'main_scientific_payload_IO':False,'no_bed_physical_or_visual_acceptance_before_actual_diagnostics':True,'case_credit':0})
(O/'preparation-source.py').write_bytes(Path(__file__).read_bytes());paths=[str(Path(v['path']).relative_to(R)) for v in adopted]+[str(p.relative_to(R)) for p in O.rglob('*') if p.is_file()]
subprocess.run(['git','add','--',*paths],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','ds02: bind five actual full801 F5 cases to unchanged138 bed audit and correct result schema','--',*paths],cwd=R,check=True)
print({'actual_original138_metadata_gates':5,'bed_requests':5,'case_credit':0,'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()})
