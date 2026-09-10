"""Prepare/reuse immutable CELL3 inputs and run the existing guarded runner."""
import argparse
import copy
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET
import numpy as np
from scripts.l1r_continuation_evidence import LAB,OUT,write,check_budget
from scripts.l1r_q2_mdbc_bridge import sha256
from scripts.l1r_input_preflight import check_input


def check_ns1_expansion(variant,dp,amplitude):
    """Keep the pass gate except for one hash-bound failure diagnostic."""
    source=OUT/'F3_CELL3_LONG_dp0p01_a1p000_noslip_visco1-AUDIT.json'
    prior=json.loads(source.read_text())
    if prior['audit_status']=='pass_diagnostic':return
    design=OUT/'F3-NS1-TIME-DIAGNOSTIC-DESIGN.json'
    if variant=='noslip_visco1_time_quarter':
        source=OUT/'F3_CELL3_LONG_dp0p01_a1p000_noslip_visco1_time-AUDIT.json'
        if not source.exists():raise ValueError('requires completed half-step diagnostic')
        prior=json.loads(source.read_text())
        design=OUT/'F3-NS1-QUARTER-TIME-DIAGNOSTIC-DESIGN.json'
    if variant in ('noslip_visco1_time','noslip_visco1_time_quarter') and dp==.01 and amplitude==1. and design.exists():
        d=json.loads(design.read_text())
        if (d['registered_before_solver'] and d['attempts']==1
            and d['predecessor_audit_sha256']==sha256(source)
            and prior['issues']==['swept_finite_wall_or_obstacle_crossing']):
            return
    raise ValueError('requires passed full-window boundary canary before expanding')


def prepare(dp=.01,amplitude=1.,variant='nominal'):
    allowed=('nominal','zero','time','output','noslip','noslip_cli_fix','noslip_visco1',
             'noslip_visco1_zero','noslip_visco1_time','noslip_visco1_time_quarter','noslip_visco1_output')
    if dp not in (.01,.0075,.006) or variant not in allowed:
        raise ValueError('unregistered numerical variant')
    ns1=variant.startswith('noslip_visco1')
    kind=(variant[len('noslip_visco1'):].lstrip('_') or 'nominal') if ns1 else variant
    if kind == 'zero': amplitude=0.
    token=str(dp).replace('.','p')
    name=f'F3_CELL3_LONG_dp{token}_a{amplitude:.3f}_{variant}'.replace('.','p')
    saved=OUT/(name+'-PREPARED.json')
    if saved.exists():
        r=json.loads(saved.read_text())
        if sha256(LAB/(r['generated_prefix']+'.xml')) != r['generated_xml_sha256']:
            raise ValueError('registered XML changed')
        check_input(r)
        return r
    check_budget()
    source=LAB/'campaigns/l1-resume/artifacts/cell3'/('F3_CELL3_plain_'+token)
    target=LAB/'campaigns/l1-resume/artifacts/cell3-long'/name
    if target.exists():
        raise ValueError('incomplete preparation exists; inspect before retry')
    shutil.copytree(source,target)
    basename=source.name
    cfl=.0125 if kind=='time_quarter' else (.025 if kind=='time' else .05)
    floor=cfl
    cadence=.002 if kind=='output' else .01
    for filename in (basename+'.xml',basename+'_Def.xml'):
        tree=ET.parse(target/filename)
        for node in tree.getroot().findall('.//cflnumber'): node.set('value',str(cfl))
        for node in tree.getroot().findall('.//parameter'):
            parameters={'TimeMax':8.35,'TimeOut':cadence,'CoefDtMin':floor}
            if variant.startswith('noslip'):parameters.update(SlipMode=2,NoPenetration=0)
            if ns1:parameters['ViscoBoundFactor']=1
            value=parameters.get(node.get('key'))
            if value is not None: node.set('value',str(value))
        tree.write(target/filename,encoding='utf-8',xml_declaration=True)
    drive=target/'CaseSloshingAccData.csv'
    if amplitude != 1.:
        values=np.loadtxt(drive,delimiter=';',comments='#')
        g=np.array([0.,0.,-9.81])
        values[:,1:4]=g+amplitude*(values[:,1:4]-g)
        values[:,4:7]*=amplitude
        np.savetxt(drive,values,delimiter=';',fmt='%.17g',header='Time;LinearAccX;LinearAccY;LinearAccZ;AngularAccX;AngularAccY;AngularAccZ')
    r=copy.deepcopy(json.loads((OUT/'F3_CELL3_plain_0p01-PREPARED.json').read_text()))
    pre=json.loads((LAB/'diagnostics/f3-audit/cell3-input-preflight.json').read_text())
    bound=next(x['boundary_particles'] for x in pre if x['case']==basename)
    n=round(.9/dp)*round(.18/dp)*round(.09/dp)
    r.update(id=name,case_id=name,phase='F3_CELL3_long_qualification',dp_m=dp,resolution=str(dp),
             time_max_s=8.35,time_out_s=cadence,cfl_number=cfl,coef_dt_min=floor,
             drive_amplitude=amplitude,variant=variant,actual_y_layers=round(.18/dp),
             control_definition='F3_CELL3_gravity_preserving_amplitude_v1',drive_sha256=sha256(drive),
             generated_prefix=str((target/basename).relative_to(LAB)),
             candidate_definition=str((target/(basename+'_Def.xml')).relative_to(LAB)),
             generated_xml_sha256=sha256(target/(basename+'.xml')),
             gencase={'total_particles':n+bound,'fluid_particles':n,'reuse_source':str(source.relative_to(LAB))},
             input_assets={p.name:sha256(p) for p in target.iterdir() if p.suffix in ('.bi4','.xml','.csv')},
             observation_design_sha256=sha256(OUT/'F3-V2-OBSERVATION-DESIGN.json'))
    if variant.startswith('noslip'):
        r.update(phase='F3_CELL3_noslip_bridge',
                 recipe_id='F3_CELL3_NS_no_projection',
                 comparison_scope='single native boundary velocity treatment contrast; not the original spatial ladder',
                 boundary_bridge_sha256=sha256(OUT/'F3-NOSLIP-BRIDGE-DESIGN.json'))
    if variant=='noslip_cli_fix' or ns1:
        r.update(solver_mode='-mdbc_noslip',expected_slip_mode='No-slip',
                 input_repair='explicit CLI no-slip flag; previous mismatched launch remains charged and invalid as a boundary contrast')
    if ns1:
        r.update(recipe_id='F3_CELL3_NS_visco1_no_projection',visco_bound_factor=1,
                 input_repair='native recommended no-slip boundary viscosity factor; fluid Visco remains 0.05',
                 boundary_bridge_sha256=sha256(OUT/'F3-NOSLIP-VISCO1-DESIGN.json'))
    r.pop('repair_of',None)
    if variant!='noslip_cli_fix' and not ns1:r.pop('input_repair',None)
    check_input(r)
    write(saved.name,r)
    return r


def main():
    p=argparse.ArgumentParser()
    p.add_argument('action',choices=['prepare','run'])
    p.add_argument('--dp',type=float,default=.01)
    p.add_argument('--amplitude',type=float,default=1.)
    p.add_argument('--variant',default='nominal')
    a=p.parse_args()
    r=prepare(a.dp,a.amplitude,a.variant)
    if a.action=='run':
        calibration=json.loads((LAB/'diagnostics/f3-audit/v2-calibration.json').read_text())
        if not calibration['calibrated'] or calibration['operator_sha256'] != sha256(LAB/'scripts/f3_observation_v2.py'):
            raise ValueError('observation candidate has not passed frozen calibration')
        if a.variant.startswith('noslip'):
            prior=json.loads((OUT/'F3_CELL3_LONG_dp0p01_a1p000_time-AUDIT.json').read_text())
            if prior['audit_status']!='quality_failed':
                raise ValueError('boundary bridge requires completed unsuccessful temporal control')
        if a.variant=='noslip_visco1':
            prior=json.loads((OUT/'F3_CELL3_LONG_dp0p01_a1p000_noslip_cli_fix-AUDIT.json').read_text())
            if prior['audit_status']!='quality_failed':raise ValueError('requires completed preceding no-slip contrast')
        if a.variant.startswith('noslip_visco1') and (a.variant!='noslip_visco1' or a.dp!=.01 or a.amplitude!=1.):
            check_ns1_expansion(a.variant,a.dp,a.amplitude)
        from scripts.l1r_branch_runner import run
        out=run(r)
        print(json.dumps({k:out.get(k) for k in ['case_id','status','audit_status','frames','issues','unknowns']}),flush=True)
    else:print(r['id'],flush=True)


if __name__=='__main__':main()
