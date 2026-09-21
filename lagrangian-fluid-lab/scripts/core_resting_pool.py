"""Register the corrected F4 resting-pool physical scope without altering v1."""
import copy
from pathlib import Path
from scripts.core_cfd import qualification_design, prepare, validate_prepared_matrix, event_horizon
from scripts.core_runtime import atomic_json, digest


def resting_design():
    design=qualification_design()
    design.update(scope_id='F4_drop_resting_pool_x_v2',revision_id='F4_resting_pool_13plus2_v2')
    design['physical_change']='pool fills the finite basin to z=.18; removes unintended initial pool free fall'
    design['canary_job']='f4-resting-pool-canary-001'
    design['continuum_geometry']['pool']={'low':[0.,0.,0.],'size':[1.2,.4,.18]}
    design['continuum_geometry']['unchanged']=False
    design['prior_scope_qualification_inherited']=False
    for cfg in design['cells']:
        cfg['pool']=dict(low=[0.,0.,0.],size=[1.2,.4,.18],mkfluid=0)
        cfg['scope_id']=design['scope_id'];cfg['case_id']='RESTING_'+cfg['case_id']
        cfg['recipe_id']='F4_resting_pool_mdbc_native_v2'
        q=cfg['parameter']['q'];cfg['physical_case_id']=cfg['lineage_group_id']=f'F4_resting_pool_q{q:.12g}'
        cfg['horizon']=event_horizon(cfg['pool'],cfg['drop'])
        # Retain the preregistered conservative 4.34 s scope-wide upper window.
        cfg['time_max_s']=4.34
        if cfg['design_cell']=='internal_time':
            cfg['dt_min_s']=1.729410723970463e-5/2
            cfg['dt_ini_s']=.000345882139640047/2
    design['actual_time_control_requirement']='at least 1.5x actual baseline integration steps over the same full horizon'
    return design


def prepare_resting_matrix(lab,output):
    output=Path(output)
    if output.exists():raise FileExistsError('new immutable matrix directory required')
    output.mkdir(parents=True)
    design=resting_design();atomic_json(output/'design.json',design)
    rows=[]
    for index,cfg in enumerate(design['cells']):
        path=output/f'cell-{index:02d}'
        result=prepare(cfg,Path(lab),path)
        rows.append({'index':index,'case_id':cfg['case_id'],'prepared':str((path/'prepared.json').resolve()),'preflight_pass':result['preflight_pass']})
        atomic_json(output/'prepared-matrix.json',{'schema':design['schema'],'design_sha256':digest(output/'design.json'),'cells':rows,'complete':len(rows)==15,'qualification_claim':'none'})
    report=validate_prepared_matrix(output);atomic_json(output/'static-validation.json',report)
    return report
