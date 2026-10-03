"""Prepare a new DP=.01 CPU-only reference of both exact F5 physical mothers.

The consumed .05/.0125 producer stays unchanged. Only this process's factory
configuration selects a fresh namespace and an additional commensurate DP.
"""
from pathlib import Path
import hashlib
import json
import ds_data02_f5_commensurate_dp_reference_010 as factory


SCRIPT=Path(__file__).resolve()

def prepare():
    factory.SCRIPT=SCRIPT
    factory.SCOPE='F5_CONTINUOUS_CELL_CENTRE_FINER_DP0P010_017'
    factory.REPAIR_ROOT=factory.FAMILY_ROOT/'initialization_repairs'/factory.SCOPE
    if factory.REPAIR_ROOT.exists():
        raise FileExistsError(factory.REPAIR_ROOT)
    factory.DP_SPECS={'dp0p010':dict(label='DP0P010',dp_m=.01,max_wall_seconds=1800)}
    factory.CASE_SPECS={key:dict(spec,resolution_id='dp0p010',case_id=f'F5_REF_{token}_NOMINAL_DP0P010_CELL_CENTRE_ROOT_017')
        for key,spec,token in [('runup_dp0p010',factory.CASE_SPECS['runup_dp00125'],'RUNUP'),('weir_dp0p010',factory.CASE_SPECS['weir_dp00125'],'WEIR')]}
    evidence=factory.prepare()
    rows=factory.write_gencase_requests()
    guard=SCRIPT.parent/'ds_data02_strict_dispatch_v1.py'
    dependency=SCRIPT.parent/'ds_data02_f5_commensurate_dp_reference_010.py'
    for row in rows:
        path=Path(row['path'])
        request=json.loads(path.read_text())
        request['attempt_id']=request['attempt_id'].replace('-010','-root-finer-017')
        request['estimated_storage_bytes']=16*1024**3
        request['launch_allowed']=True
        request['launch_owner']='root CPU only'
        request['qualification_claim']='none; actual new initialization and later frozen macro diagnostic pending'
        request['independent_case_count_increment']=0
        request['oversize_gpu_policy']='Actual total above5million requires separately bound explicitcostreview before anyfutureGPUrequest; no GPU request generated here'
        for p in [guard,dependency]:
            if str(p) not in request['input_files']:request['input_files'].append(str(p))
        request['input_sha256']={p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in request['input_files']}
        path.write_text(json.dumps(request,indent=2)+'\n')
        print(json.dumps(dict(request=str(path),expected_fluid_particles=2352000,expected_native_mass_kg=2352.,cpu_threads=4,max_wall_seconds=1800)),flush=True)
    return evidence


if __name__=='__main__':
    prepare()
