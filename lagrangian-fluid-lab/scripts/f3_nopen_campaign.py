"""One prospective native no-penetration boundary contrast, before any expansion."""
import argparse
import copy
import json
import shutil
import xml.etree.ElementTree as ET

from scripts.l1r_continuation_evidence import LAB,OUT,write,check_budget
from scripts.l1r_q2_mdbc_bridge import sha256,utc_now
from scripts.l1r_input_preflight import check_input

BASE='F3_CELL3_LONG_dp0p01_a1p000_noslip_visco1'
FINE='F3_CELL3_LONG_dp0p0075_a1p000_noslip_visco1_time_quarter'
NAME=BASE+'_nopen'
DESIGN='F3-NATIVE-NOPEN-DESIGN.json'


def verify_design():
    d=json.loads((OUT/DESIGN).read_text())
    fixed={'registered_before_solver':True,'attempts':1,'case':NAME,
           'comparison_source':BASE,'solver_timeout_seconds':1800,
           'expansion_allowed':False,'qualified':False,
           'native_velocity_displacement_correction':True,'posthoc_particle_projection':False,
           'changes':{'NoPenetration':[0,1],'CLI':['-mdbc_noslip','-mdbc_noslip:1']}}
    if any(d.get(k)!=v for k,v in fixed.items()) or set(d['required_failed_audits'])!={BASE,FINE}:
        raise ValueError('unregistered native no-penetration contrast')
    required={str(p.relative_to(LAB)) for p in native_sources()}
    if set(d['native_source_hashes'])!=required:raise ValueError('incomplete native source binding')
    for name,digest in d['required_failed_audits'].items():
        path=OUT/(name+'-AUDIT.json')
        if sha256(path)!=digest or json.loads(path.read_text())['audit_status']!='quality_failed':
            raise ValueError('predecessor audit changed or is not the registered failure')
    for name,digest in d['native_source_hashes'].items():
        if sha256(LAB/name)!=digest:raise ValueError('native source changed')
    return d


def native_sources():
    native=LAB/'vendor/official/DualSPHysics_v5.4'
    return [native/'src/source'/x for x in ('JSph.cpp','JSphCfgRun.cpp','JSphGpu_ker.cu','JSphGpuSimple_ker.cu')]+[native/'examples/mdbc/03_Sloshing/CaseSloshingLR_NSNP_Def.xml']


def register():
    if (OUT/DESIGN).exists():return verify_design()
    for name in (BASE,FINE):
        a=json.loads((OUT/(name+'-AUDIT.json')).read_text())
        if a['audit_status']!='quality_failed':raise ValueError('requires completed failed temporal/spatial diagnostics')
    sources=native_sources()
    d=dict(registered_before_solver=True,registered_at_utc=utc_now(),attempts=1,
        case=NAME,comparison_source=BASE,
        required_failed_audits={x:sha256(OUT/(x+'-AUDIT.json')) for x in (BASE,FINE)},
        native_source_hashes={str(p.relative_to(LAB)):sha256(p) for p in sources},
        evidence='Official v5.4 sloshing NSNP example enables NoPenetration. Native GPU kernel builds a near-wall velocity correction and symplectic corrector changes velocity and displacement; this is part of the new numerical recipe.',
        official_source_url='https://github.com/DualSPHysics/DualSPHysics/blob/master/src/source/JSphGpuSimple_ker.cu',
        hypothesis='Test whether the native near-wall treatment removes remaining nominal-wall crossings after timestep refinement and one spatial refinement did not.',
        changes={'NoPenetration':[0,1],'CLI':['-mdbc_noslip','-mdbc_noslip:1']},
        held_fixed=['dp=.01m','original CELL3 initial fluid and boundary particles','same normals','full amplitude=1 forcing','fixed tank coordinates','ViscoBoundFactor=1','fluid artificial Visco=.05','CFL=.05 and CoefDtMin=.05','0–8.35s','output=.01s','particle shifting disabled','unchanged hard gates and observation v2'],
        native_velocity_displacement_correction=True,posthoc_particle_projection=False,
        acceptance='All original identities and mass retained; zero exclusions, nonfinite states, nominal closed-wall crossings and tolerance exceedance over every saved frame. Full recipe qualification still requires new time/output/spatial and control-domain evidence.',
        solver_timeout_seconds=1800,expansion_allowed=False,qualified=False,
        invalidates_old_recipe_label='Do not label these results no_projection or reuse old NS1 convergence as qualification.')
    write(DESIGN,d)
    return d


def prepare():
    d=register();check_budget()
    saved=OUT/(NAME+'-PREPARED.json')
    if saved.exists():
        r=json.loads(saved.read_text())
        if r.get('boundary_bridge_sha256')!=sha256(OUT/DESIGN) or r.get('max_attempts')!=1:
            raise ValueError('prepared attempt limit or design binding differs from registration')
        prefix=LAB/r['generated_prefix']
        for name,digest in r['input_assets'].items():
            if sha256(prefix.parent/name)!=digest:raise ValueError('registered input changed')
        check_input(r);return r
    r=copy.deepcopy(json.loads((OUT/(BASE+'-PREPARED.json')).read_text()))
    source=LAB/r['generated_prefix'];target=source.parent.parent/NAME
    if target.exists():raise ValueError('incomplete preparation exists; inspect without overwrite')
    for name,digest in r['input_assets'].items():
        if sha256(source.parent/name)!=digest:raise ValueError('comparison source input changed')
    shutil.copytree(source.parent,target)
    for name in (source.name+'.xml',source.name+'_Def.xml'):
        tree=ET.parse(target/name)
        nodes=tree.getroot().findall('.//parameter[@key="NoPenetration"]')
        if len(nodes)!=1 or nodes[0].get('value')!='0':raise ValueError('unexpected source no-penetration declaration')
        before=ET.tostring(tree.getroot())
        nodes[0].set('value','1');tree.write(target/name,encoding='utf-8',xml_declaration=True)
        roundtrip=ET.parse(target/name);roundtrip.find('.//parameter[@key="NoPenetration"]').set('value','0')
        if ET.tostring(roundtrip.getroot())!=before:raise ValueError('unintended XML semantic change')
    r.update(id=NAME,case_id=NAME,phase='F3_native_nopen_boundary_diagnostic',
        variant='noslip_visco1_nopen',recipe_id='F3_CELL3_NS_visco1_native_nopen',
        solver_mode='-mdbc_noslip:1',expected_slip_mode='No-slip',expected_no_penetration=True,
        input_repair='Enable native no-penetration in XML and CLI; unchanged initial particles and forcing',
        comparison_scope='One prospective native velocity/displacement boundary correction contrast; old no-projection recipe remains failed',
        generated_prefix=str((target/source.name).relative_to(LAB)),
        candidate_definition=str((target/(source.name+'_Def.xml')).relative_to(LAB)),
        generated_xml_sha256=sha256(target/(source.name+'.xml')),
        boundary_bridge_sha256=sha256(OUT/DESIGN),solver_timeout_seconds=d['solver_timeout_seconds'],max_attempts=1,
        input_assets={p.name:sha256(p) for p in target.iterdir() if p.suffix in ('.bi4','.xml','.csv')})
    check_input(r);write(saved.name,r)
    return r


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','run']);a=p.parse_args()
    r=prepare()
    if a.action=='run':
        calibration=json.loads((LAB/'diagnostics/f3-audit/v2-calibration.json').read_text())
        if not calibration['calibrated'] or calibration['operator_sha256']!=sha256(LAB/'scripts/f3_observation_v2.py'):
            raise ValueError('observation candidate has not passed frozen calibration')
        from scripts.l1r_branch_runner import run
        result=run(r)
        print(json.dumps({k:result.get(k) for k in ('case_id','status','audit_status','frames','issues','unknowns')}),flush=True)
    else:print(r['id'],flush=True)


if __name__=='__main__':main()
