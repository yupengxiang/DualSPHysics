from pathlib import Path
import json,hashlib,subprocess,datetime
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
root=lambda n:next(H.glob(f'root*_{n:03d}'))
load=lambda p:json.loads(Path(p).read_text())
def put(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def sha(p):
    p=Path(p);assert p.suffix.lower() in {'.json','.py','.xml','.xmf','.md','.txt','.log'}
    return hashlib.sha256(p.read_bytes()).hexdigest()
ref=lambda p:{'path':str(p),'sha256':sha(p)}
typed_request=root(974)/'enabled-typed-request.json';tq=load(typed_request);ar=Path(tq['attempt_root']);tr=ar/'execution-receipt.json';tp=ar/'conversion-report.json';t=load(tp);rec=load(tr)
assert (rec['status'],rec['returncode'])==('completed',0)
assert rec['request_sha256']==sha(typed_request)
assert t['conversion_status']=='completed' and t['frames']==836 and t['particles']==179208 and t['solver_dimension']['solver_dimension']==3
assert t['partvtk_validation']['all_passed'] and all(z['passed'] and z['identity_type_mk_exact'] for z in t['partvtk_validation']['frames'])
assert t['hash_scopes']['physical_condition_sha256']==tq['physical_condition_sha256']==tq['actual_converter_scope_sha256']=='7560a18fa29742681ee567b06567ed4052da8ceb138b601e94b5223df22660f5'
assert t['hash_scopes']['physical_condition']['schema']=='ds-data-02.physical-binding.v1'
assert t['hash_scopes']['physical_condition']['physical_case_id']==tq['physical_case_id']
owner=tq['actual_converter_owner']['path'];assert sha(owner)==tq['actual_converter_owner']['sha256'];assert t['source_provenance']['owner_metadata']==ref(owner)
native_ref=tq['actual_native_dependency']['receipt'];native=native_ref['path'];assert sha(native)==native_ref['sha256'];nr=load(native);assert (nr['status'],nr['returncode'])==('completed',0);assert t['source_provenance']['solver_receipt']==ref(native)
fs=t['lifecycle']['frame_summary'];assert len(fs)==836 and fs[0]['time']==0 and fs[-1]['time']>=8.35 and all(u['time']<v['time'] for u,v in zip(fs,fs[1:]));assert t['lifecycle']['introduced_ids']=='rejected'
for i,f in enumerate(fs):
    assert f['frame']==i and f['active_particles']==179208 and f['missing_particles']==0
    assert f['type_counts']=={'0':111708,'1':0,'2':0,'3':67500}
assert t['output_hdf5']==str(ar/'trajectory.h5') and Path(t['output_hdf5']).stat().st_size<4*1024**3
source=Path('/home/jade/.codex/worktrees/ds-data-02-f3/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_followup_104_f3_next20_typed_xmf_render_source_v1')
worker=source/'workers/export_xmf.py';assert sha(worker)=='da50e26d5322b1b6f1539bca3109dfc115164427b37e1b2f86f56b153f56b0b0'
template=source/'requests/xmf/F3_STAGE1_DP006_P0800_AY0360-xmf-binding.json';b=load(template)
O=H/'root_stage1_F3_actual974_full836_explicit_v1_N3_original104_XMF_fairCPU2_977';O.mkdir(exist_ok=True);assert not (O/'enabled-full836-xmf-request.json').exists()
aid='root-stage1-f3-p0800-ay0360-actual974-full836-N3-xmf104-root977';out=D/'families/F3'/tq['case_id']/aid;assert not out.exists()
md={}
for p,digest in b['bound_metadata_sha256'].items():
    path=Path(p)
    if path.suffix in {'.json','.xml','.py','.md'}:
        assert sha(path)==digest
        md[p]=digest
    else:
        assert p==str(L/'.venv/bin/python') and digest==rec['input_hashes_at_launch'][str(path.resolve())]==rec['input_hashes_after_run'][str(path.resolve())]
        md[p]=digest
for p in [tp,tr,native,owner,typed_request,worker,template]:md[str(p)]=sha(p)
b.update(schema='ds02.f3.actual974-full836-typed-to-n3-xmf-binding.v1',
    trajectory_h5=t['output_hdf5'],trajectory_h5_sha256=t['output_sha256'],
    conversion_report=str(tp),conversion_report_sha256=sha(tp),
    typed_receipt=str(tr),typed_receipt_sha256=sha(tr),
    native_receipt=str(native),native_receipt_sha256=sha(native),
    physical_case_id=tq['physical_case_id'],physical_condition_sha256=tq['physical_condition_sha256'],
    actual_converter_scope_sha256=t['hash_scopes']['physical_condition_sha256'],
    actual_converter_scope_status='actual completed/0 Root974 report; explicit v1 owner',
    producer_scope_schema='ds-data-02.physical-binding.v1',bound_metadata_sha256=md,
    expected_frames=836,expected_particles=179208,physical_window_s=[0.0,8.35],
    source_only=False,root_actual_native884_and_typed974_completed0=True,
    root_historical839_inputs_are_source_history_not_actual_dependency=True,
    future_outputs={'execution_receipt':str(out/'execution-receipt.json'),'execution_receipt_sha256':None,
        'manifest':str(out/'xdmf/manifest.json'),'manifest_sha256':None,
        'xdmf':str(out/'xdmf/case.xmf'),'xdmf_sha256':None,'visual_decision':None})
binding=O/'actual974-full836-N3-xmf-binding.json';put(binding,b)
controller=O/'fair-xmf-controller.py';raw=(root(974)/'fair-typed-controller.py').read_text();assert 'serial_conversion=True' in raw;controller.write_text(raw)
fair=root(928)/'fair_CPU_dispatch.py';assert sha(fair)=='e2796fb88cc989278bcc4d194493f11e5ded7e6d2fb79ef37349d7ae7d8d679f'
for p in [binding,controller,fair]:md[str(p)]=sha(p)
md[t['output_hdf5']]=t['output_sha256']
q={k:tq[k] for k in ['schema','launch_owner','cwd','worktree_root','environment_policy','resource_window',
    'root_dataset_inventory_profile','root_inventory_policy_sha256','root_actual_launch_source','root_actual_launch_source_sha256']}
q.update(kind='cpu',cpu_task_kind='audit',cpu_threads=2,max_wall_seconds=7200,estimated_storage_bytes=1024**3,
    family_id='F3',case_id=tq['case_id'],physical_case_id=tq['physical_case_id'],
    physical_condition_sha256=tq['physical_condition_sha256'],attempt_id=aid,attempt_root=str(out),
    command=[str(L/'.venv/bin/python'),str(worker),'--binding',str(binding),'--output-dir','{attempt_root}/xdmf'],
    disabled=False,source_only=False,launch=True,launch_allowed=True,execution_allowed=True,root_review_required=False,
    depends_on_attempts=[tq['attempt_id'],nr['request']['attempt_id']],input_files=sorted(md),input_sha256=md,
    actual_typed_H5_SHA_from_producer_only=t['output_sha256'],source_scientific_payload_IO_by_main=False,
    full836_N3_authorized=True,q_n_granted=False,q_e_granted=False,case_credit=0)
request=O/'enabled-full836-xmf-request.json';put(request,q)
put(O/'controller-config.json',{'request':str(request),'fair_dispatch':ref(fair)})
put(O/'actual974-full836-independent-metadata-review.json',{'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'actual_typed_receipt':ref(tr),'actual_typed_report':ref(tp),'actual_native_receipt':ref(native),
    'owner':ref(owner),'physical_scope_sha256':tq['physical_condition_sha256'],'schema':'ds-data-02.physical-binding.v1',
    'typed_scientific_digest_producer_attested':t['output_sha256'],'typed_file_bytes_stat_only':Path(t['output_hdf5']).stat().st_size,
    'frames':836,'particles':179208,'all_native_UIDs_present_every_saved_frame':True,'final_time_s':fs[-1]['time'],
    'PartVTK_original_actual_validation_frames':[z['frame'] for z in t['partvtk_validation']['frames']],
    'main_scientific_payload_IO':False,'full_native_visual_status':'pending actual XMF and rendering then delegated personal review',
    'historical_839_source_references_preserved_but_not_used_as_actual_receipts':True,'case_credit':0})
(O/'preparation-source.py').write_bytes(Path(__file__).read_bytes())
paths=[str(p.relative_to(R)) for p in O.iterdir() if p.is_file()]
subprocess.run(['git','add','--',*paths],cwd=R,check=True)
subprocess.run(['git','commit','-q','-m','ds02: close first actual F3 full836 conversion and register original N3 XMF producer','--',*paths],cwd=R,check=True)
print({'root':str(O),'actual974_typed_status':'completed/0','full836_XMF_registered':True,
    'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()})
