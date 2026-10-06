from pathlib import Path
import json,hashlib,subprocess,datetime,re
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';W=Path('/home/jade/.codex/worktrees/ds-data-02-f3/DualSPHysics');D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');root=lambda n:next(H.glob(f'root*_{n:03d}'));load=lambda p:json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix.lower() in {'.json','.jsonl','.py','.md','.xml','.xmf','.txt','.log'};return hashlib.sha256(p.read_bytes()).hexdigest()
ref=lambda p:{'path':str(p),'sha256':sha(p)}
def put(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
prefix='lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_followup_125_f3_typed978981_xmf_render_handoff_v1';commit='163b8a0fd1203da6b18ae5d820385cdc38023f78';names=subprocess.check_output(['git','ls-tree','-r','--name-only',commit,'--',prefix],cwd=W,text=True).splitlines();assert 100<len(names)<200;adopted=[]
for name in names:
 assert Path(name).suffix in {'.json','.py','.md'};raw=subprocess.check_output(['git','show',f'{commit}:{name}'],cwd=W);assert raw==(W/name).read_bytes();p=R/name;assert not p.exists() or p.read_bytes()==raw;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw);adopted.append(ref(p))
P=R/prefix;O=H/'root_stage1_F3_source125_two_actual978_full836_explicit_v1_N3_original104_XMF_fairCPU2_990';O.mkdir(exist_ok=True);assert not (O/'controller-config.json').exists()
validator=P/'scripts/validate_fresh125.py';rr=subprocess.run([str(L/'.venv/bin/python'),'-B',str(validator)],capture_output=True,text=True);put(O/'actual-source125-validator.json',{'returncode':rr.returncode,'stdout':rr.stdout,'stderr':rr.stderr,'validator':ref(validator)});assert rr.returncode==0
for row in load(P/'manifest.json')['files']:assert sha(P/row['path'])==row['sha256'] and (P/row['path']).stat().st_size==row['bytes']
worker=P/'workers/export_xmf.py';assert sha(worker)=='da50e26d5322b1b6f1539bca3109dfc115164427b37e1b2f86f56b153f56b0b0'
fair=root(928)/'fair_CPU_dispatch.py';controller=O/'batch-xmf-controller.py';controller.write_text("""from pathlib import Path
import json,runpy,hashlib,time
O=Path(__file__).parent;c=json.loads((O/'controller-config.json').read_text());assert hashlib.sha256(Path(c['fair_dispatch']['path']).read_bytes()).hexdigest()==c['fair_dispatch']['sha256'];dispatch=runpy.run_path(c['fair_dispatch']['path'])['dispatch'];results=[]
for qp in c['requests']:
 assert hashlib.sha256(Path(qp).read_bytes()).hexdigest()==c['request_sha256'][qp]
 q=json.loads(Path(qp).read_text());r=dispatch(qp,serial_conversion=True);rp=Path(q['attempt_root'])/'execution-receipt.json';a=json.loads(rp.read_text()) if rp.exists() else {};mp=Path(q['attempt_root'])/'xdmf/manifest.json';m=json.loads(mp.read_text()) if mp.exists() else {}
 passed=r.returncode==0 and a.get('status')=='completed' and a.get('returncode')==0 and m.get('frames')==836 and m.get('particles')==179208 and m.get('physical_case_id')==q['physical_case_id'] and m.get('physical_condition_sha256')==q['physical_condition_sha256'] and m.get('source_h5_sha256')==q['actual_typed_H5_SHA_from_producer_only']
 z={'case_id':q['case_id'],'physical_case_id':q['physical_case_id'],'request':qp,'actual_receipt':str(rp),'actual_manifest':str(mp),'status':a.get('status'),'returncode':a.get('returncode'),'launcher_returncode':r.returncode,'actual_full836_N3_XMF_pass':passed,'stdout_tail':r.stdout[-1800:],'stderr_tail':r.stderr[-1800:],'case_credit':0};results.append(z);(O/'actual-progress.json').write_text(json.dumps({'results':results,'not_submitted':len(c['requests'])-len(results),'case_credit':0},indent=2)+'\\n');print(json.dumps(z),flush=True)
 if not passed:
  (O/'controller-result.json').write_text(json.dumps({'status':'stopped_for_primary_failure_classification','returncode':r.returncode or 1,'case_credit':0},indent=2)+'\\n');raise SystemExit(r.returncode or 1)
 time.sleep(4)
(O/'controller-result.json').write_text(json.dumps({'status':'completed','returncode':0,'actual_completed_XMF':len(results),'case_credit':0},indent=2)+'\\n')
""")
base=load(root(977)/'enabled-full836-xmf-request.json');cp=load(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_136.json');ids={load(p).get('physical_case_id',load(p)['case_id']) for p in cp['accepted_decisions']};qs=[];proofs=[];(O/'requests').mkdir(exist_ok=True);(O/'bindings').mkdir(exist_ok=True)
for suffix in ['0290','0320']:
 cid=f'F3_STAGE1_DP006_P0800_AY{suffix}';sp=P/'requests/xmf'/(cid+'-xmf-request.json');sb=P/'requests/xmf'/(cid+'-xmf-binding.json');src=load(sp);b=load(sb);assert src['disabled'] and src['source_only'] and b['typed_receipt_sha256'] is not None
 tr=Path(b['typed_receipt']);tp=Path(b['conversion_report']);ar=tr.parent;t=load(tp);rec=load(tr);tq=rec['request'];np=Path(b['native_receipt']);nr=load(np)
 assert (rec['status'],rec['returncode'])==(nr['status'],nr['returncode'])==('completed',0) and sha(tr)==b['typed_receipt_sha256'] and sha(tp)==b['conversion_report_sha256'] and sha(np)==b['native_receipt_sha256']
 assert tq['case_id']==cid==b['case_id'] and tq['physical_case_id']==b['physical_case_id'] not in ids
 assert t['conversion_status']=='completed' and t['frames']==836 and t['particles']==179208 and t['solver_dimension']['solver_dimension']==3
 assert t['hash_scopes']['physical_condition_sha256']==b['physical_condition_sha256']==b['actual_converter_scope_sha256']==tq['physical_condition_sha256'] and t['hash_scopes']['physical_condition']['schema']=='ds-data-02.physical-binding.v1'
 assert t['hash_scopes']['physical_condition']['physical_case_id']==b['physical_case_id'] and t['partvtk_validation']['all_passed'] and all(f['passed'] and f['identity_type_mk_exact'] for f in t['partvtk_validation']['frames'])
 assert t['source_provenance']['solver_receipt']==ref(np) and t['output_sha256']==b['trajectory_h5_sha256'] and t['output_hdf5']==b['trajectory_h5'] and Path(t['output_hdf5']).stat().st_size<4*1024**3
 for k in ['owner_metadata','gencase_receipt','generated_xml']:
  f=t['source_provenance'][k];assert sha(f['path'])==f['sha256']
 fs=t['lifecycle']['frame_summary'];assert len(fs)==836 and fs[0]['time']==0 and fs[-1]['time']>=8.35 and all(a['time']<z['time'] for a,z in zip(fs,fs[1:])) and t['lifecycle']['introduced_ids']=='rejected'
 for i,f in enumerate(fs):assert f['frame']==i and f['active_particles']==179208 and f['missing_particles']==0 and f['type_counts']=={'0':111708,'1':0,'2':0,'3':67500}
 md=b['bound_metadata_sha256'].copy()
 bad=[p for p,digest in md.items() if sha(p)!=digest]
 if bad:
  assert suffix=='0320' and len(bad)==1 and bad[0]==str(W/prefix/'metadata/case-snapshots'/f'{cid}.json')
  snap=load(bad[0]);st=snap['source_typed_status_at_snapshot'];producer=snap['typed_producer_evidence']
  assert snap['case_id']==cid and snap['physical_case_id']==b['physical_case_id'] and snap['physical_condition_sha256']==b['physical_condition_sha256']
  assert st['terminal_completed0'] and st['receipt_path']==str(tr) and st['receipt_sha256']==sha(tr) and st['conversion_report_path']==str(tp) and st['conversion_report_sha256']==sha(tp)
  assert producer['frames']==836 and producer['particles']==179208 and producer['trajectory_h5_sha256_reported_by_typed_producer']==t['output_sha256'] and snap['native_terminal_evidence']['receipt_sha256']==sha(np)
  proof=O/'actual-source125-AY0320-stale-snapshot-binding-failure-and-grounded-rebind.json'
  put(proof,{'source_binding':ref(sb),'original_expected_snapshot_sha256':md[bad[0]],'actual_byte_exact_committed_snapshot':ref(bad[0]),'actual_typed_receipt':ref(tr),'actual_typed_report':ref(tp),'snapshot_typed_native_physical_counts_and_producer_H5_attestation_independently_exact':True,'original_source125_unchanged':True,'original_binding_hash_failure_preserved':True,'original_source_validator_does_not_cover_binding_bound_metadata_map':True,'only_this_snapshot_hash_rebound_in_new_enabled_binding':True,'science_worker_and_scientific_inputs_unchanged':True,'scientific_payload_IO':False,'case_credit':0})
  md[bad[0]]=sha(bad[0]);b['bound_metadata_sha256']=md.copy()
 for p,digest in md.items():assert sha(p)==digest
 aid=f'root-stage1-f3-p0800-ay{suffix}-actual978-full836-N3-xmf104-source125-root990';out=D/'families/F3'/cid/aid;assert not out.exists()
 b.update(schema='ds02.f3.actual978-full836-typed-to-n3-xmf-binding.v1',source_only=False,actual_converter_scope_status='Actual completed0 typed978 report explicitv1',root_future_XMF_attempt_id=aid,future_outputs={'execution_receipt':str(out/'execution-receipt.json'),'execution_receipt_sha256':None,'manifest':str(out/'xdmf/manifest.json'),'manifest_sha256':None,'xdmf':str(out/'xdmf/case.xmf'),'xdmf_sha256':None,'visual_decision':None})
 bp=O/'bindings'/(cid+'-actual978-xmf-binding.json');put(bp,b)
 for p in [bp,sp,sb,worker,controller,fair,O/'actual-source125-validator.json']:md[str(p)]=sha(p)
 md[t['output_hdf5']]=t['output_sha256'];py=str(L/'.venv/bin/python');md[py]=rec['input_hashes_at_launch'][str(Path(py).resolve())];assert md[py]==rec['input_hashes_after_run'][str(Path(py).resolve())]
 q={k:base[k] for k in ['schema','launch_owner','cwd','worktree_root','environment_policy','root_dataset_inventory_profile','root_inventory_policy_sha256','root_actual_launch_source','root_actual_launch_source_sha256']};q.update(kind='cpu',cpu_task_kind='audit',cpu_threads=2,max_wall_seconds=7200,estimated_storage_bytes=1024**3,family_id='F3',case_id=cid,physical_case_id=b['physical_case_id'],physical_condition_sha256=b['physical_condition_sha256'],attempt_id=aid,attempt_root=str(out),command=[py,str(worker),'--binding',str(bp),'--output-dir','{attempt_root}/xdmf'],disabled=False,source_only=False,launch=True,launch_allowed=True,execution_allowed=True,root_review_required=False,depends_on_attempts=[tq['attempt_id'],nr['request']['attempt_id']],input_files=sorted(md),input_sha256=md,actual_typed_H5_SHA_from_producer_only=t['output_sha256'],source_scientific_payload_IO_by_main=False,full836_N3_authorized=True,q_n_granted=False,q_e_granted=False,case_credit=0)
 qp=O/'requests'/(cid+'-enabled-full836-xmf-request.json');put(qp,q);qs.append(str(qp));proofs.append({'case_id':cid,'physical_case_id':b['physical_case_id'],'typed_receipt':ref(tr),'typed_report':ref(tp),'native_receipt':ref(np),'physical_scope_sha256':b['physical_condition_sha256'],'all836_UIDs_present':True,'final_time_s':fs[-1]['time'],'H5_SHA_producer_only':t['output_sha256'],'source_binding':ref(sb),'enabled_request':ref(qp),'scientific_payload_IO_by_primary':False})
put(O/'controller-config.json',{'requests':qs,'request_sha256':{p:sha(p) for p in qs},'fair_dispatch':ref(fair),'effective_shared_serial_conversion_concurrency':1,'case_credit':0});put(O/'source125-adoption-two-actual978-independent-QI-review.json',{'source_commit':commit,'adopted_files':adopted,'cases':proofs,'source125_all19_original_validator_pass':True,'science_payload_IO_by_primary':False,'future_XMF_SHA_null':True,'case_credit':0});(O/'preparation-source.py').write_bytes(Path(__file__).read_bytes());paths=[str(Path(x['path']).relative_to(R)) for x in adopted]+[str(p.relative_to(R)) for p in O.rglob('*') if p.is_file()];subprocess.run(['git','add','--',*paths],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','ds02: register two actual F3 full836 N3 XMF products using original104 worker and source125 closure','--',*paths],cwd=R,check=True);print({'root':str(O),'source_files':len(adopted),'XMF_cases':len(qs),'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()})
