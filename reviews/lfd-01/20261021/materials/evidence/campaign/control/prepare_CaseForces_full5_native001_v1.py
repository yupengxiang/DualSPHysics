"""Materialize one complete real-data child; first native fingerprints are child-owned."""
from pathlib import Path
import argparse,ast,copy,datetime,hashlib,json,runpy,resource
P=Path(__file__).resolve().parents[1]
ROOT=Path('/data/nas/jade/Simulation/DualSPHysics/lfd-01')
H=runpy.run_path(str(P/'control/prepare_F3_existing601_mass_task_actual001_v1.py'))
pin,publish,canonical=(H[k] for k in ('pin','publish','canonical'))
Q=P/'requests/CaseForces-full5-native001-v1'
CASE='LFD01_CASEFORCES_FULL5_NATIVE';LEAF='LFD01_CONVERT_001'
AID='infra/'+CASE+'/'+LEAF;JOB='LFD01_CASEFORCES_FULL5_NATIVE_001';OUT=ROOT/'runs'/AID
SQ=P/'requests/CaseForces-full5-baseline-solver001-v3'

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--source',required=True);ap.add_argument('--review',required=True);args=ap.parse_args()
    source=pin(args.source);review=pin(args.review);rv=json.loads(Path(args.review).read_bytes())
    assert rv['status'].startswith('accepted'),rv['status']
    tree=ast.parse(Path(args.source).read_bytes());assert any(isinstance(n,ast.FunctionDef) and n.name=='main' for n in tree.body)
    closure=json.loads((SQ/'ACTUAL_SOLVER_TERMINAL_CLOSURE_V1.json').read_bytes())
    assert closure['status']=='completed_solver_pending_actual_G1_G2'
    req=json.loads((P/'requests/CaseForces-initial-facts001-v1/request.json').read_bytes());grant=json.loads((P/'requests/CaseForces-initial-facts001-v1/grant.json').read_bytes())
    basecfg=json.loads((P/'decisions/CASEFORCES_EXISTING_DECODER_INITIAL_FACTS_CONTRACT_V1.json').read_bytes())
    asset=json.loads((P/'requests/F2-official-CaseForces-gencase001-v1/ACTUAL_ASSET_PARENT_NEGATIVE_CLOSURE_V1.json').read_bytes())
    oldqa=json.loads((P/'requests/F6-full101-PartVTK-compare-actual001-v1/request.json').read_bytes())
    partvtk=next({k:r[k] for k in ('path','bytes','sha256')} for r in oldqa['source_bindings'] if r['role']=='official_partvtk')
    assert not Q.exists() and not OUT.exists() and not (ROOT/'runs/.lfd01-control/jobs'/JOB).exists()
    cfg=dict(schema='lfd01.Root.CaseForces.full5-child.v1',case_id='LFD01_F2_OFFICIAL_CASEFORCES_DP020_FULL5',output_root=str(OUT),science_contract=pin(P/'decisions/CASEFORCES_FULL5_SCIENCE_CONTRACT_V1.json'),protocol_adoption=pin(P/'decisions/CASEFORCES_FULL5_PROTOCOL_ADOPTION_V1.json'),initial_facts_closure=pin(P/'requests/CaseForces-initial-facts001-v1/ACTUAL_INITIAL_FACTS_CLOSURE_V1.json'),source_preflight=closure['source_preflight'],asset_closure=pin(P/'requests/F2-official-CaseForces-gencase001-v1/ACTUAL_ASSET_PARENT_NEGATIVE_CLOSURE_V1.json'),gencase_closure=pin(P/'requests/F2-official-CaseForces-gencase001-v1/ACTUAL_ASSET_PARENT_NEGATIVE_CLOSURE_V1.json'),solver_request=closure['request'],solver_grant=closure['grant'],solver_receipt=closure['receipt'],solver_closure=pin(SQ/'ACTUAL_SOLVER_TERMINAL_CLOSURE_V1.json'),generated_xml=asset['generated_xml'],decoder=basecfg['decoder'],legacy_source=basecfg['legacy_source'],partvtk=partvtk,data_root=dict(path=str(ROOT/'runs/F2/LFD01_F2_OFFICIAL_CASEFORCES_DP020_FULL5/LFD01_SOLVER_001/data'),inspection_only=True,bytes=None,sha256=None,max_total_bytes=2*1024**3),expected=dict(particles=44063),outputs=dict(hdf5=dict(path=str(OUT/'particles.h5')),history=dict(path=str(OUT/'history.json')),report=dict(path=str(OUT/'result.json'))),science_credit=0,core_credit=0)
    Q.mkdir();cr=publish(Q/'child-contract.json',cfg)
    rows=copy.deepcopy(req['source_bindings'][:12])
    def add(role,ref,deferred=False):
        ref={k:ref[k] for k in ('path','bytes','sha256')}
        if any(r['path']==ref['path'] for r in rows):
            assert any(all(r[k]==ref[k] for k in ref) and r['deferred']==deferred for r in rows);return
        if not deferred:assert pin(ref['path'])==ref
        rows.append(dict(ref,role=role,deferred=deferred))
    add('native_pipeline_source',source);add('native_pipeline_contract',cr);add('nonauthor_method_review',review)
    for key in ['science_contract','protocol_adoption','initial_facts_closure','source_preflight','asset_closure','gencase_closure','solver_request','solver_grant','solver_receipt','solver_closure','legacy_source']:add(key,cfg[key])
    for key in ['generated_xml','decoder','partvtk']:add(key,cfg[key],True)
    # The producer-owned native directory is a first-observation target, never a fabricated hashed normal input.
    manifest=publish(Q/'manifest.json',dict(schema='lfd01.Root.CaseForces.full5-native-manifest.v1',source=source,contract=cr,review=review,producer_closure=cfg['solver_closure'],inspection_only_target=cfg['data_root'],source_bindings=rows,output_root=str(OUT),science_credit=0,core_credit=0));add('frozen_native_manifest',manifest)
    normal=[r['path'] for r in rows if not r['deferred']];sha=hashlib.sha256(canonical(rows)).hexdigest()
    req.update(family_id='infra',case_id=CASE,attempt_id=LEAF,reservation_id=AID,controller_job_id=JOB,request_path=str(Q/'request.json'),grant_path=str(Q/'grant.json'),output_root=str(OUT),tmpdir=str(OUT/'.tmp'),cpu_task_kind='audit',command=[req['command'][0],'-B',source['path'],'--contract',cr['path'],'--contract-bytes',str(cr['bytes']),'--contract-sha256',cr['sha256'],'--output-root',str(OUT)],source_bindings=rows,source_bindings_sha256=sha,input_files=normal,normal_input_paths=normal,max_wall_seconds=900,cpu_threads=1,affinity_cpus=[0],ram_limit_bytes=64*1024**3,nas_peak_bytes=64*1024**3,estimated_storage_bytes=2*1024**3,max_output_bytes=2*1024**3,max_stdout_bytes=16384,required_dispatch_environment=dict(PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',PYTHONOPTIMIZE='0',TMPDIR=str(OUT/'.tmp')),dataset_bindings=[],manifest_binding=manifest,purpose='One all-saved-frame CaseForces full5 real native conversion and factual G1/tasks through existing decoder+legacyHDF+selectedPartVTK. Native target first inventory performed in owned heavy child. No solver rerun/no G2 or core grant.',science_credit=0,core_credit=0)
    rr=publish(Q/'request.json',req)
    grant.update(family_id='infra',case_id=CASE,leaf_attempt_id=LEAF,attempt_id=AID,reservation_id=AID,controller_job_id=JOB,tranche_id=JOB,request_path=rr['path'],request_sha256=rr['sha256'],source_bindings=rows,source_bindings_sha256=sha,input_files=normal,normal_input_paths=normal,stage='CaseForces_full5_real_native_HDF_G1_tasks',allocation=dict(gpu_seconds=0,cpu_core_seconds=900,new_storage_bytes=2*1024**3,solver_attempts=0),issued_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),non_author_source_review=review,non_author_payload_review=review,permitted_scope=req['purpose'])
    grant.pop('payload_sha256',None);grant['payload_sha256']=hashlib.sha256(canonical(grant)).hexdigest();gr=publish(Q/'grant.json',grant)
    print(json.dumps(publish(Q/'MATERIALIZATION.json',dict(schema='lfd01.Root.CaseForces.full5-native-materialization.v1',status='prepared_pending_live_shared_admission',request=rr,grant=gr,manifest=manifest,source=source,contract=cr,method_review=review,normal_rows=len(normal),deferred_rows=len(rows)-len(normal),normal_bytes=sum(r['bytes'] for r in rows if not r['deferred']),output_root=str(OUT),reservation_id=AID,controller_job_id=JOB,root_native_ELF_generatedXML_HDF_or_array_access=False,science_credit=0,core_credit=0,root_self_cpu_pending_infra=sum(resource.getrusage(resource.RUSAGE_SELF)[:2])))))

if __name__=='__main__':main()
