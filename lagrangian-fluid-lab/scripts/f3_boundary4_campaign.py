"""Run only the preregistered four-layer nominal contrast after temporal failure."""
import argparse
import copy
import json
from scripts.l1r_continuation_evidence import LAB,OUT,write
from scripts.l1r_q2_mdbc_bridge import sha256
from scripts.l1r_input_preflight import check_input


def prepare():
    pre=json.loads((OUT/'F3-BOUNDARY4-INPUT-PREFLIGHT.json').read_text())
    if pre['status']!='passed_input_only' or not pre['fluid_positions_exactly_unchanged']:
        raise ValueError('boundary input preflight not passed')
    prefix=LAB/pre['candidate_prefix']
    for filename,digest in pre['assets'].items():
        if sha256(prefix.parent/filename)!=digest:raise ValueError('prepared boundary input changed')
    if pre['design_sha256']!=sha256(OUT/'F3-BOUNDARY4-DESIGN.json'):
        raise ValueError('boundary design changed')
    name=prefix.name
    r=copy.deepcopy(json.loads((OUT/'F3_CELL3_LONG_dp0p01_a1p000_noslip_visco1-PREPARED.json').read_text()))
    r.update(id=name,case_id=name,phase='F3_CELL4_noslip_bridge',recipe_id='F3_CELL4_NS_visco1_no_projection',
        generated_prefix=pre['candidate_prefix'],candidate_definition=str(prefix.relative_to(LAB))+'_Def.xml',
        generated_xml_sha256=sha256(prefix.with_suffix('.xml')),input_assets=pre['assets'],
        gencase=dict(total_particles=pre['fluid_count']+pre['new_boundary_count'],fluid_particles=pre['fluid_count'],boundary_particles=pre['new_boundary_count']),
        boundary_bridge_sha256=pre['design_sha256'],boundary_layer_count=4,
        comparison_scope='single boundary support-depth contrast; nominal physical walls and fluid initial points unchanged',
        input_repair='add fourth external boundary layer to cover native DDT recommended kernel support depth')
    check_input(r)
    path=OUT/(name+'-PREPARED.json')
    if path.exists():
        if json.loads(path.read_text())!=r:raise ValueError('existing prepared record differs')
    else:write(path.name,r)
    return r


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','run']);a=p.parse_args()
    if a.action=='run':
        predecessor=OUT/'F3_CELL3_LONG_dp0p01_a1p000_noslip_visco1_time-AUDIT.json'
        if (OUT/'F3_CELL3_LONG_dp0p01_a1p000_noslip_visco1_time_quarter-PREPARED.json').exists():
            predecessor=OUT/'F3_CELL3_LONG_dp0p01_a1p000_noslip_visco1_time_quarter-AUDIT.json'
        if not predecessor.exists() or json.loads(predecessor.read_text())['audit_status']!='quality_failed':
            raise ValueError('requires completed unsuccessful latest NS1 temporal diagnostic before selecting this contrast')
        calibration=json.loads((LAB/'diagnostics/f3-audit/v2-calibration.json').read_text())
        if not calibration['calibrated'] or calibration['operator_sha256']!=sha256(LAB/'scripts/f3_observation_v2.py'):
            raise ValueError('frozen observation calibration missing or changed')
    r=prepare()
    if a.action=='prepare':print(r['id']);return
    from scripts.l1r_branch_runner import run
    out=run(r)
    print(json.dumps({k:out.get(k) for k in ['case_id','status','audit_status','frames','issues','unknowns']}),flush=True)


if __name__=='__main__':main()
