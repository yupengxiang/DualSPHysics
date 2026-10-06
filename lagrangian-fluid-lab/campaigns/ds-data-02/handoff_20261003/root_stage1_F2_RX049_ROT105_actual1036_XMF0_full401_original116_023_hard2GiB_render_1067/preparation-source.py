from pathlib import Path
import json,hashlib,runpy,subprocess,xml.etree.ElementTree as ET,datetime
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
root=lambda n:next(H.glob(f'root*_{n:03d}'));load=lambda p:json.loads(Path(p).read_text())
def put(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def sha(p):
    p=Path(p);assert p.suffix.lower() not in {'.h5','.hdf5','.bi4','.ibi4','.csv','.dat','.vtk','.vtu','.npy','.npz'}
    return hashlib.sha256(p.read_bytes()).hexdigest()
ref=lambda p:{'path':str(p),'sha256':sha(p)}
xq=load(next((root(1036)/'requests').glob('*.json')));b=load(xq['command'][xq['command'].index('--binding')+1]);xr=Path(xq['attempt_root'])/'execution-receipt.json';rec=load(xr)
assert (rec['status'],rec['returncode'])==('completed',0)
xp=Path(xq['attempt_root'])/'xdmf/manifest.json';x=load(xp);xml=Path(x['xdmf']);t=load(b['conversion_report'])
assert x['frames']==t['frames']==401 and x['particles']==t['particles']==418104
assert x['source_h5_sha256']==t['output_sha256'] and x['source_h5_read_only'] and x['physical_condition_sha256']==t['hash_scopes']['physical_condition_sha256']==b['physical_condition_sha256']
assert x['producer_scope_schema']=='legacy-owner-scope.v0' and x['physical_case_id']==b['physical_case_id']
assert x['xdmf_sha256']==sha(xml)
assert rec['input_hashes_at_launch'][b['trajectory_h5']]==rec['input_hashes_after_run'][b['trajectory_h5']]==t['output_sha256']
fs=t['lifecycle']['frame_summary'];grids=ET.parse(xml).findall('.//Grid[@GridType="Uniform"]');times=x['actual_time_s'];assert len(grids)==len(fs)==len(times)==401
assert times==[f['time'] for f in fs]==[float(g.find('Time').get('Value')) for g in grids]
assert times[0]==0 and times[-1]>=4.0 and all(a<b for a,b in zip(times,times[1:]))
assert x['fields']['position']['shape']==x['fields']['velocity']['shape']==[401,418104,3]
for i,(g,f) in enumerate(zip(grids,fs)):
    assert f['frame']==i and f['active_particles']+f['missing_particles']==418104 and f['missing_type_counts'].get('3',0)==f['missing_particles']
    assert g.find('Geometry').get('GeometryType')=='XYZ' and g.find('Geometry/DataItem').get('Dimensions')=='418104 3'
    vv=next(v for v in g.findall('Attribute') if v.get('Name').lower()=='velocity');assert vv.get('AttributeType')=='Vector' and vv.find('DataItem').get('Dimensions')=='418104 3'
cp=load(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_162.json');assert b['physical_case_id'] not in {load(p).get('physical_case_id',load(p)['case_id']) for p in cp['accepted_decisions']}
O=H/'root_stage1_F2_RX049_ROT105_actual1036_XMF0_full401_original116_023_hard2GiB_render_1067';O.mkdir(exist_ok=False)
proof=O/'actual1036-full401-XMF-and-actual-typed-independent-review.json'
put(proof,{'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'actual_XMF_receipt':ref(xr),
    'actual_XMF_manifest':ref(xp),'actual_XMF_XML':ref(xml),'actual_typed_report':ref(b['conversion_report']),
    'actual_typed_receipt':ref(b['typed_receipt']),'actual_native_receipt':ref(b['native_receipt']),
    'physical_case_id':b['physical_case_id'],'physical_condition_sha256':b['physical_condition_sha256'],
    'all401_geometry_and_velocity_N3_and_exact_actual_times':True,'all401_native_identity_axis_preserved_with_recorded_fluid_omissions':True,'final_missing_particles':fs[-1]['missing_particles'],'omission_states_and_causes_unknown':True,
    'actual_time_window_s':[times[0],times[-1]],'source_H5_real_XMF_runner_pre_post_digest':t['output_sha256'],
    'primary_scientific_payload_IO':False,'visual_status':'pending full401 render then delegated personal contact/key review','case_credit':0})
base=load(root(984)/'enabled-full801-render-request.json');w=load(base['command'][-1]);worker=Path(base['command'][base['command'].index('--worker')+1]);assert sha(worker)=='5d577e4b28e62906472bfba30ad445685f804be4ba5d8bab44b4bab3d32e1621'
api=runpy.run_path(str(worker));aid='root-stage1-f2-rx049-rot105-actual1036-full401-116-023-nvme-hard2gib-root1067';ar=D/'families/F2'/b['case_id']/aid;assert not ar.exists();rid=f"F2/{b['case_id']}/{aid}"
controller=O/'fair-render-controller.py';controller.write_bytes((root(984)/'fair-render-controller.py').read_bytes())
md={str(p):sha(p) for p in [worker,Path(w['renderer']),Path(w['pvpython']),Path(base['command'][1]),controller,root(928)/'fair_CPU_dispatch.py',proof,xp,xml,xr,
    Path(b['native_receipt']),Path(b['conversion_report']),Path(b['typed_receipt']),Path(xq['command'][xq['command'].index('--binding')+1]),
    root(142)/'launch.py',root(142)/'root_home_floor_inventory_policy.py',L/'scripts/ds_data02_runtime_v2.py',L/'scripts/ds_data02_strict_dispatch_v1.py',root(64)/'resource-window-approval.json']}
w.update(family_id='F2',case_id=b['case_id'],physical_case_id=b['physical_case_id'],manifest=str(xp),attempt_id=aid,reservation_id=rid,current_attempt_id=rid,
    home_output=str(ar/'render'),nvme_root='/tmp/ds02-visual-render-cache-root1067',expected_frames=401,expected_particles=418104,expected_contact_sheets=17,
    keyframe_indices=[0,50,100,150,200,250,300,350,400],input_files=sorted(md),input_sha256=md,
    actual_converter_scope_sha256=b['physical_condition_sha256'],canonical_source_scope_sha256=b['canonical_source_physical_condition_sha256'])
api['validate_request'](w,execution=True);assert api['_manifest_metadata'](w)['manifest']==w['manifest'];wp=O/'enabled-render-wrapper.json';put(wp,w)
outer={**md,str(wp):sha(wp),b['trajectory_h5']:t['output_sha256']};q=base.copy()
q.update(family_id='F2',case_id=b['case_id'],physical_case_id=b['physical_case_id'],attempt_id=aid,attempt_root=str(ar),physical_condition_sha256=b['physical_condition_sha256'],
    actual_converter_scope_sha256=b['physical_condition_sha256'],source_h5_producer_sha256=t['output_sha256'],
    command=[str(L/'.venv/bin/python'),base['command'][1],'--worker',str(worker),'--request',str(wp)],input_files=sorted(outer),input_sha256=outer,
    root_scope='Original actual full401 legacy-scope F2 XMF to original116/023 complete render; no scientific recipe/input mutation, no visual or numerical credit before actual evidence.',
    full401_authorized=True,case_credit=0)
qp=O/'enabled-full401-render-request.json';put(qp,q);put(O/'controller-config.json',{'request':str(qp),'fair_dispatch':ref(root(928)/'fair_CPU_dispatch.py'),'case_credit':0})
(O/'preparation-source.py').write_bytes(Path(__file__).read_bytes());paths=[str(p.relative_to(R)) for p in O.iterdir() if p.is_file()]
subprocess.run(['git','add','--',*paths],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','ds02: independently close actual F2 full401 XMF and register complete bounded ParaView render','--',*paths],cwd=R,check=True)
print({'root':str(O),'full401_actual_XMF_pass':True,'full401_render_registered':True,'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()})
